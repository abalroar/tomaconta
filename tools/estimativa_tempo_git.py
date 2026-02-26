#!/usr/bin/env python3
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections import defaultdict

GAP_MINUTES = 90
MIN_SESSION_MINUTES = 20
END_BUFFER_MINUTES = 15
MAX_SESSION_HOURS = 4


@dataclass
class Commit:
    sha: str
    dt: datetime
    author: str
    subject: str


@dataclass
class Session:
    date: str
    start: datetime
    end: datetime
    commits: list[Commit]

    @property
    def estimated_minutes(self) -> int:
        span_minutes = (self.end - self.start).total_seconds() / 60
        estimated = span_minutes + END_BUFFER_MINUTES
        estimated = max(estimated, MIN_SESSION_MINUTES)
        estimated = min(estimated, MAX_SESSION_HOURS * 60)
        return int(round(estimated))


def load_commits() -> list[Commit]:
    cmd = [
        "git",
        "log",
        "--reverse",
        "--date=iso-strict",
        "--pretty=format:%H|%ad|%an|%s",
    ]
    raw = subprocess.check_output(cmd, text=True)
    commits: list[Commit] = []
    for line in raw.splitlines():
        sha, date_str, author, subject = line.split("|", 3)
        if subject.startswith("Merge "):
            continue
        dt = datetime.fromisoformat(date_str)
        commits.append(Commit(sha=sha, dt=dt, author=author, subject=subject))
    return commits


def build_sessions(commits: list[Commit]) -> list[Session]:
    sessions: list[Session] = []
    current: Session | None = None

    for c in commits:
        c_date = c.dt.date().isoformat()
        if current is None:
            current = Session(date=c_date, start=c.dt, end=c.dt, commits=[c])
            continue

        gap = c.dt - current.end
        if c_date != current.date or gap > timedelta(minutes=GAP_MINUTES):
            sessions.append(current)
            current = Session(date=c_date, start=c.dt, end=c.dt, commits=[c])
        else:
            current.end = c.dt
            current.commits.append(c)

    if current is not None:
        sessions.append(current)

    return sessions


def format_minutes(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h{m:02d}"


def main() -> None:
    commits = load_commits()
    sessions = build_sessions(commits)

    daily_minutes = defaultdict(int)
    daily_sessions = defaultdict(int)
    daily_commits = defaultdict(int)
    author_minutes = defaultdict(int)

    for s in sessions:
        mins = s.estimated_minutes
        daily_minutes[s.date] += mins
        daily_sessions[s.date] += 1
        daily_commits[s.date] += len(s.commits)

        per_author = defaultdict(int)
        for c in s.commits:
            per_author[c.author] += 1
        total = len(s.commits)
        for author, count in per_author.items():
            author_minutes[author] += round(mins * (count / total))

    total_minutes = sum(daily_minutes.values())
    total_commits = sum(daily_commits.values())

    lines: list[str] = []
    lines.append("# Estimativa diária de tempo trabalhado (base GitHub)")
    lines.append("")
    lines.append("## Metodologia usada")
    lines.append(f"- Fonte: histórico de commits do Git (`git log`), ignorando merges.")
    lines.append(f"- Uma sessão ativa é encerrada quando há **mais de {GAP_MINUTES} min** sem commit ou muda o dia.")
    lines.append(f"- Duração de cada sessão = intervalo entre 1º e último commit da sessão + **{END_BUFFER_MINUTES} min** de buffer.")
    lines.append(f"- Duração mínima por sessão: **{MIN_SESSION_MINUTES} min**.")
    lines.append(f"- Duração máxima por sessão: **{MAX_SESSION_HOURS}h** (evita inflar sessões muito longas sem evidência).")
    lines.append("- Esta é uma estimativa conservadora para apresentação gerencial, não um apontamento oficial de horas.")
    lines.append("")

    lines.append("## Resumo executivo")
    lines.append(f"- Dias com atividade: **{len(daily_minutes)}**")
    lines.append(f"- Sessões ativas identificadas: **{len(sessions)}**")
    lines.append(f"- Commits considerados (sem merges): **{total_commits}**")
    lines.append(f"- Tempo total estimado no projeto: **{format_minutes(total_minutes)}**")
    lines.append("")

    lines.append("## Totais por autor (estimados)")
    lines.append("| Autor | Tempo estimado |")
    lines.append("|---|---:|")
    for author, mins in sorted(author_minutes.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"| {author} | {format_minutes(mins)} |")
    lines.append("")

    lines.append("## Estimativa diária")
    lines.append("| Data | Sessões ativas | Commits | Tempo estimado |")
    lines.append("|---|---:|---:|---:|")
    for day in sorted(daily_minutes):
        lines.append(
            f"| {day} | {daily_sessions[day]} | {daily_commits[day]} | {format_minutes(daily_minutes[day])} |"
        )

    report_path = "docs/estimativa_tempo_git.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Relatório gerado em {report_path}")


if __name__ == "__main__":
    main()
