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

USER = "forit-tech"
API = "https://api.github.com"
OUT = pathlib.Path("assets/analytics.svg")
SNAPSHOT = pathlib.Path("analytics/snapshots/latest.json")
TOKEN = os.getenv("GITHUB_TOKEN", "")


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
    groups = [
        ("Data Science / ML / AI", ["data", "analysis", "science", "machine", "ml", "model", "drift", "ai", "llm", "rag", "pandas", "polars", "sklearn", "scikit"]),
        ("Data Engineering", ["etl", "pipeline", "clickhouse", "airflow", "spark", "warehouse", "postgres", "database"]),
        ("Backend", ["fastapi", "spring", "api", "backend", "server", "bot", "django", "flask"]),
        ("Frontend / Product", ["react", "typescript", "vite", "desktop", "frontend", "app"]),
    ]
    scores = {name: sum(1 for word in words if word in text) for name, words in groups}
    best = max(scores, key=scores.get)
    return best if scores[best] else "Другое"


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
    commits: list[dt.datetime] = []
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
                    commits.append(dt.datetime.fromisoformat(raw.replace("Z", "+00:00")))
            if len(batch) < 100:
                break
            commit_page += 1

    total_lang = sum(language_bytes.values()) or 1
    lang_top = language_bytes.most_common(5)
    other_lang = sum(language_bytes.values()) - sum(v for _, v in lang_top)
    if other_lang > 0:
        lang_top.append(("Другое", other_lang))

    total_repo = len(repos) or 1
    data_share = round(100 * categories["Data Science / ML / AI"] / total_repo)
    tech_index = entropy_index(language_bytes)

    current90 = sum(1 for c in commits if c >= now - dt.timedelta(days=90))
    previous90 = sum(1 for c in commits if now - dt.timedelta(days=180) <= c < now - dt.timedelta(days=90))
    velocity = None if previous90 == 0 else round(100 * (current90 - previous90) / previous90)

    weekday = collections.Counter(c.weekday() for c in commits)
    weekday_names = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    active_day = weekday_names[max(weekday, key=weekday.get)] if weekday else "—"

    month_counts = []
    for offset in range(11, -1, -1):
        year = now.year
        month = now.month - offset
        while month <= 0:
            month += 12
            year -= 1
        month_counts.append(sum(1 for c in commits if c.year == year and c.month == month))
    max_month = max(month_counts) if month_counts else 1
    spark = "".join(f'<rect x="{56+i*40}" y="{238-(v/max_month if max_month else 0)*58:.1f}" width="24" height="{max(3,(v/max_month if max_month else 0)*58):.1f}" rx="4" class="spark"/>' for i,v in enumerate(month_counts))

    cat_order = ["Data Science / ML / AI", "Data Engineering", "Backend", "Frontend / Product", "Другое"]
    cat_svg = "\n".join(bar(56, 340+i*48, 255, round(100*categories[name]/total_repo), name, f"{round(100*categories[name]/total_repo)}%") for i,name in enumerate(cat_order))
    lang_svg = "\n".join(bar(520, 340+i*48, 250, round(100*v/total_lang), name, f"{100*v/total_lang:.1f}%") for i,(name,v) in enumerate(lang_top[:5]))

    velocity_text = "—" if velocity is None else f"{velocity:+d}%"
    generated = now.strftime("%d.%m.%Y %H:%M UTC")

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="650" viewBox="0 0 900 650">
<style>
.bg{{fill:#11111b;stroke:#313244;stroke-width:1.5}} .title{{fill:#cdd6f4;font:700 24px 'Segoe UI',sans-serif}} .sub{{fill:#a6adc8;font:13px 'Segoe UI',sans-serif}} .metric{{fill:#cba6f7;font:700 30px 'Segoe UI',sans-serif}} .metricLabel{{fill:#a6adc8;font:12px 'Segoe UI',sans-serif}} .section{{fill:#f5c2e7;font:700 13px 'Segoe UI',sans-serif;letter-spacing:1.2px}} .label{{fill:#cdd6f4;font:12px 'Segoe UI',sans-serif}} .value{{fill:#bac2de;font:11px 'Segoe UI',sans-serif}} .track{{fill:#313244}} .bar{{fill:#cba6f7}} .spark{{fill:#89b4fa}} .line{{stroke:#313244;stroke-width:1}}
</style>
<rect x="1" y="1" width="898" height="648" rx="22" class="bg"/>
<text x="56" y="62" class="title">МОЙ GITHUB В ДАННЫХ</text>
<text x="56" y="86" class="sub">автоматическая аналитика публичных репозиториев · без сторонних stats-сервисов</text>
<line x1="56" y1="108" x2="844" y2="108" class="line"/>
<text x="56" y="150" class="metric">{len(repos)}</text><text x="56" y="170" class="metricLabel">публичных репозиториев</text>
<text x="290" y="150" class="metric">{len(commits)}</text><text x="290" y="170" class="metricLabel">коммитов за 12 месяцев</text>
<text x="515" y="150" class="metric">{data_share}%</text><text x="515" y="170" class="metricLabel">Data Science / ML / AI</text>
<text x="740" y="150" class="metric">{tech_index}</text><text x="740" y="170" class="metricLabel">индекс разнообразия технологий</text>
<text x="56" y="210" class="section">АКТИВНОСТЬ ЗА 12 МЕСЯЦЕВ</text>{spark}
<text x="56" y="292" class="sub">темп за 90 дней: {velocity_text} · самый активный день: {active_day}</text>
<text x="56" y="324" class="section">НАПРАВЛЕНИЯ ПРОЕКТОВ</text><text x="520" y="324" class="section">ТЕХНОЛОГИИ ПО ОБЪЁМУ КОДА</text>
{cat_svg}
{lang_svg}
<line x1="56" y1="594" x2="844" y2="594" class="line"/>
<text x="56" y="622" class="sub">Обновлено: {generated} · методология: analytics/METHODOLOGY.md</text>
</svg>'''

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(svg, encoding="utf-8")
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(json.dumps({
        "generated_at": now.isoformat(),
        "public_repositories": len(repos),
        "commits_365d": len(commits),
        "categories": categories,
        "language_bytes": language_bytes,
        "data_ml_ai_share_pct": data_share,
        "technology_diversity_index": tech_index,
        "velocity_90d_pct": velocity,
        "most_active_weekday_utc": active_day,
    }, ensure_ascii=False, indent=2, default=dict), encoding="utf-8")


if __name__ == "__main__":
    main()
