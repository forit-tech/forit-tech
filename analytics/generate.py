from __future__ import annotations

import collections
import datetime as dt
import html
import json
import math
import os
import pathlib
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

USER = "forit-tech"
API = "https://api.github.com"
OUT = pathlib.Path("assets/analytics.svg")
SNAPSHOT = pathlib.Path("analytics/snapshots/latest.json")
TOKEN = os.getenv("GITHUB_TOKEN", "")
LOCAL_TZ = ZoneInfo("Europe/Moscow")


def api(path: str):
    req = urllib.request.Request(API + path)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "forit-tech-profile-analytics")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def classify(repo: dict, languages: dict[str, int]) -> str:
    text = " ".join([
        repo.get("name", ""),
        repo.get("description") or "",
        " ".join(repo.get("topics") or []),
        " ".join(languages.keys()),
    ]).lower()

    rules = [
        ("AI / LLM", ["llm", "rag", "ollama", "gguf", "transformer", "embedding", "prompt", "agent", "ai", "modelarena"]),
        ("Machine Learning", ["machine learning", "ml", "sklearn", "scikit", "classifier", "regression", "clustering", "drift", "model"]),
        ("Data Science", ["data science", "analysis", "analytics", "pandas", "polars", "numpy", "scipy", "statistics", "dataset", "dataarena"]),
        ("Data Engineering", ["etl", "pipeline", "clickhouse", "airflow", "spark", "warehouse", "postgres", "database", "sql"]),
        ("Backend / Product", ["fastapi", "spring", "api", "backend", "server", "bot", "django", "flask", "react", "typescript", "vite", "desktop", "frontend", "app"]),
    ]

    scores = {name: sum(1 for word in words if word in text) for name, words in rules}
    best_score = max(scores.values(), default=0)
    if best_score == 0:
        return "Другое"
    for name, _ in rules:
        if scores[name] == best_score:
            return name
    return "Другое"


def entropy_index(counter: collections.Counter[str]) -> int:
    values = [v for v in counter.values() if v > 0]
    if len(values) <= 1:
        return 0
    total = sum(values)
    h = -sum((v / total) * math.log(v / total) for v in values)
    return round(100 * h / math.log(len(values)))


def esc(value) -> str:
    return html.escape(str(value))


def bar(x, y, width, pct, label, value):
    fill = max(0, min(width, width * pct / 100))
    return f'''<text x="{x}" y="{y}" class="label">{esc(label)}</text>
<rect x="{x}" y="{y+10}" width="{width}" height="8" rx="4" class="track"/>
<rect x="{x}" y="{y+10}" width="{fill:.1f}" height="8" rx="4" class="bar"/>
<text x="{x+width+12}" y="{y+18}" class="value">{esc(value)}</text>'''


def heatmap_svg(commits_local: list[dt.datetime]) -> tuple[str, str]:
    counts = [[0 for _ in range(8)] for _ in range(7)]
    for c in commits_local:
        counts[c.weekday()][c.hour // 3] += 1

    max_count = max((v for row in counts for v in row), default=0)
    weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    hour_labels = ["00", "03", "06", "09", "12", "15", "18", "21"]
    parts = []
    x0, y0 = 557, 673
    cell_w, cell_h, gap = 27, 17, 6

    for i, label in enumerate(hour_labels):
        parts.append(f'<text x="{x0+i*(cell_w+gap)+13}" y="{y0-14}" text-anchor="middle" class="heatAxis">{label}</text>')
    for day, label in enumerate(weekdays):
        y = y0 + day * (cell_h + gap)
        parts.append(f'<text x="{x0-18}" y="{y+13}" text-anchor="end" class="heatAxis">{label}</text>')
        for bucket in range(8):
            value = counts[day][bucket]
            level = 0 if max_count == 0 or value == 0 else max(1, min(4, math.ceil(4 * value / max_count)))
            x = x0 + bucket * (cell_w + gap)
            parts.append(f'<rect x="{x}" y="{y}" width="{cell_w}" height="{cell_h}" rx="4" class="heat{level}"/>')

    hour_counter = collections.Counter(c.hour // 3 for c in commits_local)
    if not hour_counter:
        active_time = "—"
    else:
        bucket = max(hour_counter, key=hour_counter.get)
        start = bucket * 3
        end = (start + 3) % 24
        active_time = f"{start:02d}:00–{end:02d}:00"
    return "\n".join(parts), active_time


def main():
    repos = []
    page = 1
    while True:
        batch = api(f"/users/{USER}/repos?per_page=100&page={page}&sort=updated")
        repos.extend([r for r in batch if not r.get("fork") and not r.get("private")])
        if len(batch) < 100:
            break
        page += 1

    language_bytes = collections.Counter()
    categories = collections.Counter()
    commits_utc: list[dt.datetime] = []
    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=365)

    for repo in repos:
        name = repo["name"]
        langs = api(f"/repos/{USER}/{urllib.parse.quote(name)}/languages")
        language_bytes.update(langs)
        categories[classify(repo, langs)] += 1

        commit_page = 1
        while commit_page <= 5:
            path = f"/repos/{USER}/{urllib.parse.quote(name)}/commits?author={USER}&since={since.isoformat()}&per_page=100&page={commit_page}"
            batch = api(path)
            if not isinstance(batch, list):
                break
            for c in batch:
                raw = (((c.get("commit") or {}).get("author") or {}).get("date"))
                if raw:
                    commits_utc.append(dt.datetime.fromisoformat(raw.replace("Z", "+00:00")))
            if len(batch) < 100:
                break
            commit_page += 1

    commits_local = [c.astimezone(LOCAL_TZ) for c in commits_utc]
    total_lang = sum(language_bytes.values()) or 1
    lang_top = language_bytes.most_common(4)
    other_lang = sum(language_bytes.values()) - sum(v for _, v in lang_top)
    if other_lang > 0:
        lang_top.append(("Другое", other_lang))

    total_repo = len(repos) or 1
    data_categories = {"Data Science", "Machine Learning", "AI / LLM", "Data Engineering"}
    data_repo_count = sum(categories[name] for name in data_categories)
    data_share = round(100 * data_repo_count / total_repo)
    tech_index = entropy_index(language_bytes)
    tech_count = sum(1 for v in language_bytes.values() if v > 0)

    current90 = sum(1 for c in commits_utc if c >= now - dt.timedelta(days=90))
    previous90 = sum(1 for c in commits_utc if now - dt.timedelta(days=180) <= c < now - dt.timedelta(days=90))
    velocity = None if previous90 == 0 else round(100 * (current90 - previous90) / previous90)

    month_counts = []
    now_local = now.astimezone(LOCAL_TZ)
    for offset in range(11, -1, -1):
        year = now_local.year
        month = now_local.month - offset
        while month <= 0:
            month += 12
            year -= 1
        month_counts.append(sum(1 for c in commits_local if c.year == year and c.month == month))
    max_month = max(month_counts) if month_counts else 1
    spark = "".join(
        f'<rect x="{56+i*40}" y="{238-(v/max_month if max_month else 0)*58:.1f}" width="24" height="{max(3,(v/max_month if max_month else 0)*58):.1f}" rx="4" class="spark"/>'
        for i, v in enumerate(month_counts)
    )

    cat_order = ["Data Science", "Machine Learning", "AI / LLM", "Data Engineering", "Backend / Product", "Другое"]
    cat_svg = "\n".join(
        bar(56, 342 + i * 45, 260, round(100 * categories[name] / total_repo), name, f"{round(100 * categories[name] / total_repo)}%")
        for i, name in enumerate(cat_order)
    )
    lang_svg = "\n".join(
        bar(520, 342 + i * 45, 250, round(100 * v / total_lang), name, f"{100 * v / total_lang:.1f}%")
        for i, (name, v) in enumerate(lang_top[:5])
    )

    heat_svg, active_time = heatmap_svg(commits_local)
    main_direction = max(cat_order, key=lambda name: categories[name]) if repos else "—"
    velocity_text = "—" if velocity is None else f"{velocity:+d}%"
    generated = now.strftime("%d.%m.%Y %H:%M UTC")

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="910" viewBox="0 0 900 910">
<style>
.bg{{fill:#11111b;stroke:#313244;stroke-width:1.5}} .sub{{fill:#a6adc8;font:13px 'Segoe UI',sans-serif}} .metric{{fill:#cba6f7;font:700 31px 'Segoe UI',sans-serif}} .metricLabel{{fill:#a6adc8;font:12px 'Segoe UI',sans-serif}} .section{{fill:#f5c2e7;font:700 13px 'Segoe UI',sans-serif;letter-spacing:1.2px}} .label{{fill:#cdd6f4;font:12px 'Segoe UI',sans-serif}} .value{{fill:#bac2de;font:11px 'Segoe UI',sans-serif}} .track{{fill:#313244}} .bar{{fill:#cba6f7}} .spark{{fill:#89b4fa}} .line{{stroke:#313244;stroke-width:1}} .summaryKey{{fill:#a6adc8;font:12px 'Segoe UI',sans-serif}} .summaryValue{{fill:#cdd6f4;font:600 12px 'Segoe UI',sans-serif}} .heatAxis{{fill:#7f849c;font:10px 'Segoe UI',sans-serif}} .heat0{{fill:#313244}} .heat1{{fill:#45475a}} .heat2{{fill:#585b70}} .heat3{{fill:#89b4fa}} .heat4{{fill:#cba6f7}}
</style>
<rect x="1" y="1" width="898" height="908" rx="22" class="bg"/>
<text x="56" y="58" class="metric">{len(repos)}</text><text x="56" y="80" class="metricLabel">публичных репозиториев</text>
<text x="322" y="58" class="metric">{data_share}%</text><text x="322" y="80" class="metricLabel">проектов Data / ML / AI</text>
<text x="615" y="58" class="metric">{tech_count}</text><text x="615" y="80" class="metricLabel">технологий в публичном коде</text>
<line x1="56" y1="108" x2="844" y2="108" class="line"/>
<text x="56" y="142" class="section">АКТИВНОСТЬ ЗА 12 МЕСЯЦЕВ</text>{spark}
<text x="56" y="270" class="sub">темп за последние 90 дней: {velocity_text}</text>
<text x="56" y="314" class="section">НАПРАВЛЕНИЯ ПРОЕКТОВ</text><text x="520" y="314" class="section">ТЕХНОЛОГИИ</text>
{cat_svg}
{lang_svg}
<line x1="56" y1="626" x2="844" y2="626" class="line"/>
<text x="56" y="660" class="section">РИТМ РАБОТЫ</text>
{heat_svg}
<text x="56" y="690" class="summaryKey">Самое активное время</text><text x="220" y="690" class="summaryValue">{esc(active_time)} MSK</text>
<text x="56" y="722" class="summaryKey">Основное направление</text><text x="220" y="722" class="summaryValue">{esc(main_direction)}</text>
<text x="56" y="754" class="summaryKey">Доля Data / ML / AI</text><text x="220" y="754" class="summaryValue">{data_share}%</text>
<text x="56" y="786" class="summaryKey">Индекс разнообразия</text><text x="220" y="786" class="summaryValue">{tech_index} / 100</text>
<line x1="56" y1="842" x2="844" y2="842" class="line"/>
<text x="56" y="872" class="sub">Автоматически по публичным репозиториям · обновлено {generated}</text>
</svg>'''

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(svg, encoding="utf-8")
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps({
        "generated_at": now.isoformat(),
        "timezone": "Europe/Moscow",
        "public_repositories": len(repos),
        "commits_365d": len(commits_utc),
        "categories": categories,
        "language_bytes": language_bytes,
        "technology_count": tech_count,
        "data_ml_ai_share_pct": data_share,
        "technology_diversity_index": tech_index,
        "velocity_90d_pct": velocity,
        "most_active_time_msk": active_time,
        "main_direction": main_direction,
    }, ensure_ascii=False, indent=2, default=dict), encoding="utf-8")


if __name__ == "__main__":
    main()
