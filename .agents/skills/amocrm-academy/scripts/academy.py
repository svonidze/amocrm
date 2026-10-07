#!/usr/bin/env python3
"""Small local helpers; never call a browser, downloader, or paid API."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit, urlunsplit

START = "<!-- amocrm-academy:toc:start -->"
END = "<!-- amocrm-academy:toc:end -->"
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

def load_catalog(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    seen_modules = set()
    for module in data["modules"]:
        number = str(module["number"])
        if not number.isdecimal() or int(number) < 1 or number in seen_modules:
            raise ValueError("Module numbers must be unique positive integers")
        seen_modules.add(number)
        seen = set()
        for lesson in module["lessons"]:
            slug = lesson["slug"]
            if not SLUG.fullmatch(slug) or slug in seen:
                raise ValueError("Lesson slugs must be safe and unique per module")
            seen.add(slug)
            url = urlsplit(lesson["url"])
            if (url.scheme != "https" or url.hostname not in ("amocrm.ru", "www.amocrm.ru")
                    or url.query or url.fragment or url.username or url.password
                    or not url.path.startswith("/partners/cabinet/academy/modules/")
                    or url.path.rstrip("/").split("/")[-1] != slug):
                raise ValueError("Catalog must contain canonical amoCRM lesson URLs")
            if not lesson["title"].strip():
                raise ValueError("Lesson title is empty")
            if re.search(r"[?&](?:p|token|key|password|secret)=", lesson.get("error", ""), re.I):
                raise ValueError("Error text must not contain access parameters")
    return data

def select(data, number, query):
    modules = [m for m in data["modules"] if str(m["number"]) == str(number)]
    if len(modules) != 1:
        raise ValueError("Requested module is absent from the catalog")
    lessons = modules[0]["lessons"]
    if query == "all":
        return lessons
    if query.isdecimal():
        position = int(query)
        if 1 <= position <= len(lessons):
            return [lessons[position - 1]]
        raise ValueError("Video number is outside this module's playlist")
    matches = [l for l in lessons if query.rstrip("/").casefold() in
               (l["slug"].casefold(), l["title"].casefold(), l["url"].rstrip("/").casefold())]
    if len(matches) != 1:
        raise ValueError("Video selection is missing or ambiguous; clarify it")
    return matches

def normalize_rutube(url):
    parts = urlsplit(url.strip())
    if (parts.scheme != "https" or parts.hostname not in ("rutube.ru", "www.rutube.ru")
            or parts.username or parts.password):
        raise ValueError("Expected an HTTPS Rutube URL")
    path = parts.path
    private = re.fullmatch(r"/play/embed/private/([a-z0-9]{32})/?", path)
    if private:
        path = "/video/private/" + private[1] + "/"
    if not re.fullmatch(r"/(?:video(?:/private)?/[a-z0-9]{32}|(?:play/)?embed/(?:[a-z0-9]{32}|[0-9]+))/?", path):
        raise ValueError("Unsupported Rutube path; inspect the page")
    return urlunsplit(("https", "rutube.ru", path, parts.query, ""))

def nonempty(path):
    return path.is_file() and path.stat().st_size > 0

def cell(text):
    return str(text).replace("|", "&#124;").replace("\n", " ").replace("\r", " ")

def index_text(data, root):
    lines = [START, "## Оглавление", ""]
    for module in sorted(data["modules"], key=lambda m: int(m["number"])):
        lines += [f"### Модуль {module['number']}: {cell(module['title'])}", "",
                  "| № | Видео | Длительность | Материалы | Состояние |",
                  "| --- | --- | --- | --- | --- |"]
        for i, lesson in enumerate(module["lessons"], 1):
            relative = Path("modules") / str(module["number"]) / lesson["slug"]
            directory = root / relative
            links = [f"[{label}]({(relative / name).as_posix()})"
                     for name, label in (("page.md", "Страница"), ("transcript.md", "Транскрипт"), ("summary.md", "Конспект"))
                     if nonempty(directory / name)]
            complete = all(nonempty(directory / f) for f in ("video.mp4", "page.md", "transcript.md", "summary.md"))
            if lesson.get("error"):
                status = "Ошибка: " + cell(lesson["error"])
            elif complete:
                status = "Готово"
            elif links or nonempty(directory / "video.mp4"):
                status = "Частично"
            else:
                status = "Не обработано"
            title = cell(lesson["title"]).replace("[", "&#91;").replace("]", "&#93;")
            lines.append(f"| {i} | [{title}]({lesson['url']}) | {cell(lesson.get('duration', 'Неизвестна'))} | "
                         + (" · ".join(links) or "") + f" | {status} |")
        lines.append("")
    lines.append(END)
    return "\n".join(lines)

def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)

def update_index(data, root):
    root = Path(root).resolve()
    path = root / "README.md"
    body = path.read_text(encoding="utf-8") if path.exists() else "# Академия amoCRM\n\nМатериалы модулей партнерской Академии: сведения страниц, транскрипты и учебные конспекты.\n"
    known = set(re.findall(r"^### Модуль ([0-9]+):", body, re.M))
    known.update(p.name for p in (root / "modules").glob("*") if p.is_dir() and p.name.isdecimal())
    supplied = {str(module["number"]) for module in data["modules"]}
    if known - supplied:
        raise ValueError("Catalog omits known modules; merge their metadata before updating the index")
    start_count, end_count = body.count(START), body.count(END)
    if (start_count, end_count) == (0, 0):
        body = body.rstrip() + "\n\n" + index_text(data, root) + "\n"
    elif (start_count, end_count) == (1, 1) and body.index(START) < body.index(END):
        body = body[:body.index(START)] + index_text(data, root) + body[body.index(END) + len(END):]
    else:
        raise ValueError("README has invalid TOC markers; preserve it and repair explicitly")
    atomic_write(path, body)

def whisper_markdown(payload, output, source, misc_root, model="turbo", duration=None):
    sys.path.insert(0, str(Path(misc_root).resolve()))
    from audio.models import TranscriptionResult, TranscriptionSegment
    from audio.renderers import generate_markdown
    segments = []
    previous = -1.0
    for raw in payload.get("segments", []):
        text = raw["text"].strip()
        start, end = float(raw["start"]), float(raw["end"])
        if not (math.isfinite(start) and math.isfinite(end) and 0 <= start <= end and start >= previous):
            raise ValueError("Invalid or unordered Whisper timestamps")
        previous = start
        if text:
            segments.append(TranscriptionSegment(start, end, text, None, 0))
    if not segments:
        raise ValueError("Whisper returned no speech segments")
    duration = float(duration) if duration is not None else max(s.end_sec for s in segments)
    if not math.isfinite(duration) or duration <= 0 or duration + 0.5 < max(s.end_sec for s in segments):
        raise ValueError("Transcript exceeds the media duration")
    result = TranscriptionResult("whisper", model, str(source), str(payload.get("language", "auto")),
                                 duration, " ".join(s.text for s in segments), segments)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=output.parent, suffix=".md")
    os.close(fd)
    try:
        generate_markdown(result, Path(name), Path(source).name, False)
        os.replace(name, output)
    finally:
        Path(name).unlink(missing_ok=True)

def whisper_command(audio, output, misc_root, executable, model="turbo", language="auto"):
    sys.path.insert(0, str(Path(misc_root).resolve()))
    from audio.run_whisper import build_command
    command = build_command(Path(executable), [Path(audio)], Path(output), model=model,
                            language=language, task="transcribe", output_format="json",
                            word_timestamps=False, extra_args=[])
    # Whisper's argparse rejects literal "None"; omission enables detection.
    if language == "auto":
        position = command.index("--language")
        del command[position:position + 2]
    return command

def self_test(misc_root):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        url = "https://www.amocrm.ru/partners/cabinet/academy/modules/product-introduction/"
        data = {"modules": [{"number": 2, "title": "Модуль", "lessons": [
            {"slug": "first", "title": "Первое", "url": url + "first", "duration": "0:10"},
            {"slug": "second", "title": "Второе", "url": url + "second", "duration": "0:20"}]}]}
        catalog = root / "catalog.json"
        catalog.write_text(json.dumps(data), encoding="utf-8")
        data = load_catalog(catalog)
        assert len(select(data, 2, "all")) == 2
        for query in ("1", "first", "Первое", url + "first"):
            assert select(data, 2, query)[0]["slug"] == "first"
        try:
            select(data, 2, "3")
        except ValueError:
            pass
        else:
            raise AssertionError("Out-of-range selection accepted")
        duplicate = json.loads(json.dumps(data))
        duplicate["modules"][0]["lessons"][1]["title"] = "Первое"
        try:
            select(duplicate, 2, "Первое")
        except ValueError:
            pass
        else:
            raise AssertionError("Ambiguous title accepted")
        embed = "https://rutube.ru/play/embed/private/" + "a" * 32 + "/?p=a%2Bb"
        assert normalize_rutube(embed).endswith("/?p=a%2Bb")
        assert "/video/private/" in normalize_rutube(embed)
        command = whisper_command("audio.mp3", root, misc_root, sys.executable)
        assert "--language" not in command
        assert command[command.index("--fp16") + 1] == "False"
        assert command[command.index("--model") + 1] == "turbo"
        lesson = root / "modules/2/first"
        lesson.mkdir(parents=True)
        (root / "README.md").write_text("# Manual\n\nKeep this.\n", encoding="utf-8")
        for name in ("page.md", "summary.md", "video.mp4"):
            (lesson / name).write_text("fixture", encoding="utf-8")
        payload = {"language": "ru", "segments": [
            {"start": 0, "end": 4, "text": "Первый фрагмент."},
            {"start": 32, "end": 35, "text": "Второй фрагмент."}]}
        whisper_markdown(payload, lesson / "transcript.md", "video.mp4", misc_root, duration=40)
        transcript = (lesson / "transcript.md").read_text()
        assert "[00:00:32]" in transcript and "Второй фрагмент." in transcript
        update_index(data, root)
        before = (root / "README.md").read_bytes()
        update_index(data, root)
        assert before == (root / "README.md").read_bytes()
        assert "Готово" in before.decode() and "Не обработано" in before.decode()
        assert "Keep this." in before.decode()
        partial = {"modules": []}
        try:
            update_index(partial, root)
        except ValueError:
            pass
        else:
            raise AssertionError("Incomplete catalog discarded an existing module")
        assert before == (root / "README.md").read_bytes()
        data["modules"][0]["lessons"][1]["error"] = "Скачивание недоступно"
        update_index(data, root)
        assert "Ошибка: Скачивание недоступно" in (root / "README.md").read_text()
        before = (lesson / "transcript.md").read_bytes()
        try:
            whisper_markdown({"segments": []}, lesson / "transcript.md", "video.mp4", misc_root)
        except ValueError:
            pass
        else:
            raise AssertionError("Empty transcript accepted")
        assert before == (lesson / "transcript.md").read_bytes()
    print("Self-test passed: selection, private URL, Whisper Markdown, resume index, partial failure")

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pick = commands.add_parser("select")
    pick.add_argument("catalog", type=Path)
    pick.add_argument("--module", required=True)
    group = pick.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true")
    group.add_argument("--video")
    index = commands.add_parser("index")
    index.add_argument("catalog", type=Path)
    index.add_argument("--root", required=True, type=Path)
    normalize = commands.add_parser("normalize-url")
    normalize.add_argument("input", type=Path)
    normalize.add_argument("--output", required=True, type=Path)
    adapter = commands.add_parser("whisper-md")
    adapter.add_argument("input", type=Path)
    adapter.add_argument("--output", required=True, type=Path)
    adapter.add_argument("--source", required=True)
    adapter.add_argument("--model", default="turbo")
    adapter.add_argument("--duration", type=float)
    adapter.add_argument("--misc-root", type=Path, default=Path("/Users/serg/Projects/misc"))
    runner = commands.add_parser("whisper-run")
    runner.add_argument("input", type=Path)
    runner.add_argument("--output-dir", required=True, type=Path)
    runner.add_argument("--misc-root", type=Path, default=Path("/Users/serg/Projects/misc"))
    runner.add_argument("--model", default="turbo")
    runner.add_argument("--language", default="auto")
    runner.add_argument("--whisper-exe", type=Path)
    check = commands.add_parser("self-test")
    check.add_argument("--misc-root", type=Path, default=Path("/Users/serg/Projects/misc"))
    args = parser.parse_args()
    try:
        if args.command == "select":
            print(json.dumps(select(load_catalog(args.catalog), args.module, "all" if args.all else args.video),
                             ensure_ascii=False, indent=2))
        elif args.command == "index":
            update_index(load_catalog(args.catalog), args.root)
        elif args.command == "normalize-url":
            atomic_write(args.output, normalize_rutube(args.input.read_text()) + "\n")
        elif args.command == "whisper-md":
            whisper_markdown(json.loads(args.input.read_text()), args.output, args.source,
                             args.misc_root, args.model, args.duration)
        elif args.command == "whisper-run":
            executable = args.whisper_exe or shutil.which("whisper")
            if not executable or not Path(executable).is_file():
                raise ValueError("Whisper executable not found; supply --whisper-exe")
            if not args.input.is_file():
                raise ValueError("Audio input not found")
            args.output_dir.mkdir(parents=True, exist_ok=True)
            sys.exit(subprocess.run(whisper_command(args.input, args.output_dir, args.misc_root,
                                                  executable, args.model, args.language)).returncode)
        else:
            self_test(args.misc_root)
    except (ValueError, KeyError, TypeError, OSError, ImportError) as exc:
        parser.exit(1, f"Error: {exc}\n")

if __name__ == "__main__":
    main()
