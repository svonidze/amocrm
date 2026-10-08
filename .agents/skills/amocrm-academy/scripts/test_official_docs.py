"""Offline checks for extraction, safe reuse, scope and partial failures."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import official_docs as docs

URL = "https://www.amocrm.ru/support/tasks/create_new_task"
HTML = '<h1 class="feature__header_main">Задача</h1><div class="content-block__faq-container"><div class="faq__item_content"><p>Задача хранит срок и исполнителя. Это содержимое документа, которое нужно сохранить полностью.</p><form>Private account<input value="secret"></form><script>secret()</script></div></div>'


class DocumentationTests(unittest.TestCase):
    def test_extraction_excludes_account_shell_and_keeps_body(self):
        title, body, children = docs.extract(HTML, URL)
        self.assertEqual(title, "Задача")
        self.assertIn("нужно сохранить полностью", body)
        self.assertNotIn("secret", body)
        self.assertNotIn("Private account", body)
        self.assertEqual(children, [])
        with self.assertRaises(ValueError):
            docs.extract('<h1>Войти</h1><input name="password">', URL)

    def test_section_scope_and_url_deduplication(self):
        html = '<h2 class="faq__section_head">Задачи</h2><div class="content-block__faq-container"><a class="faq__item_link" href="/support/tasks/create_new_task/?utm_source=a#x">Создать задачу</a><a class="faq__item_link" href="/support/tasks/create_new_task">Создать задачу</a></div><a href="/support/analytics">Other menu</a>'
        self.assertEqual(docs.extract(html, "https://www.amocrm.ru/support/tasks")[2], [URL])
        for unsafe in ["https://example.com/support/tasks", "http://www.amocrm.ru/support/tasks", "https://www.amocrm.ru/partners/account", "https://www.amocrm.ru/support/../account"]:
            with self.assertRaises(ValueError):
                docs.canonical(unsafe)

    def test_existing_snapshot_is_reused_and_manual_file_is_protected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = docs.destination(root, URL)
            path.parent.mkdir(parents=True)
            path.write_text("# Задача\n" + docs.MARKER + "\nUser annotation\n")
            with patch.object(docs, "urlopen", side_effect=AssertionError("Unexpected request")):
                docs.save(root, URL)
            self.assertIn("User annotation", path.read_text())
            path.write_text("# Manual document")
            with self.assertRaises(ValueError):
                docs.save(root, URL, refresh=True)

    def test_partial_failure_keeps_success_and_index_prose(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            page = root / "page.md"
            other = "https://www.amocrm.ru/support/tasks/edit_task"
            page.write_text(f"[one]({URL}) [two]({other})")
            def fake_save(root, url, refresh):
                if url == URL:
                    raise ValueError("Unavailable body")
                path = docs.destination(root, url)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("# Saved second document")
                return "Saved", []
            (root / "docs").mkdir()
            (root / "docs/README.md").write_text("User introduction\n")
            with patch.object(docs, "save", side_effect=fake_save), patch("sys.argv", ["official_docs.py", str(page), "--root", str(root)]):
                self.assertTrue(docs.main())
            report = json.loads((root / "work/official-docs/report.json").read_text())
            self.assertEqual(len(report["documents"]), 1)
            self.assertEqual(len(report["errors"]), 1)
            self.assertTrue(docs.destination(root, other).exists())
            self.assertIn("User introduction", (root / "docs/README.md").read_text())


if __name__ == "__main__":
    unittest.main()
