# Команды и формат материалов

Все команды выполняются с проверенными абсолютными путями. Корень проекта
определить по расположению скила, misc по доступному репозиторию
(в этой среде /Users/serg/Projects/misc). Не выводить значения ключей из .env.

## Каталог и выбор

В work/catalog.json хранить только данные публичных URL страниц amoCRM,
без src Rutube, ключей доступа или cookies. Порядок lessons является порядком
живого плейлиста; модули сохранять без потери ранее известных записей.

~~~json
{
  "modules": [{
    "number": 2,
    "title": "Введение в продукт",
    "lessons": [{
      "slug": "amocrm-entities",
      "title": "Сущности amoCRM: Контакт, Сделка, Компания",
      "duration": "26:38",
      "url": "https://www.amocrm.ru/partners/cabinet/academy/modules/product-introduction/amocrm-entities"
    }]
  }]
}
~~~

У записи видео необязательное поле error с краткой причиной и этапом:
например «Транскрибация: запрос завершился тайм-аутом, результат неизвестен».
Не вставлять в него сырые логи или приватные URL. После успешного исправления
убрать error. Новые страницы модуля добавить в каталог по их URL, не создавать
каталоги для невыбранных видео.

~~~bash
python3 "$skill_helper" select "$project_root/work/catalog.json" --module 2 --all
python3 "$skill_helper" select "$project_root/work/catalog.json" --module 2 --video 'Воронка продаж'
python3 "$skill_helper" select "$project_root/work/catalog.json" --module 2 --video 2
python3 "$skill_helper" index "$project_root/work/catalog.json" --root "$project_root"
~~~

skill_helper означает .agents/skills/amocrm-academy/scripts/academy.py.
select читает только каталог и ничего не скачивает. Неточное название
или неоднозначный выбор требует уточнения, не выбора первого совпадения.
index сохраняет текст README вне маркеров своего оглавления.
При работе с несколькими модулями каталог включает все известные модули:
перед index восстановить пропущенные записи из page.md и текущего README.

## Сохранение страницы

page.md начинается с заголовка видео, затем содержит:
- номер и название модуля, порядковый номер видео;
- автора, длительность, канонический URL amoCRM и дату чтения;
- цели и существенные сведения описания в пересказе;
- ссылки на справку и другие относящиеся к уроку материалы.

Брать эти данные из текущей страницы. Не включать сведения аккаунта,
ссылки чата, соседних модулей и приватный Rutube URL.
Описание, сформированное с сайта, не дополнять фактами из транскрипта:
различия источников должны оставаться различимыми.

## Загрузка и проверка видео

Через документированный CUA прочитать iframe src. Например, после наблюдения
iframe использовать read-only locator/evaluateAll и фильтрацию по rutube.ru.
Не обращаться к внутренним переменным сайта или cookies через evaluate.
При DOM-only поверхности использовать locator; при недоступности браузерного
расширения прочитать accessibility tree нативного Chrome или src в исходнике
через UI. Не выполнять произвольный JavaScript через DevTools.

Секретный iframe URL записать в work/embed-url.txt. Нормализовать в другой
игнорируемый файл, не выводя адрес:
~~~bash
python3 "$skill_helper" normalize-url "$project_root/work/embed-url.txt" --output "$project_root/work/video-url.txt"
yt-dlp --no-playlist --batch-file "$project_root/work/video-url.txt" -f 'b[ext=mp4]/b' --remux-video mp4 -o "$lesson_dir/video.%(ext)s" > "$stage_dir/download.log" 2>&1
ffprobe -v error -show_entries format=duration:stream=codec_type -of json "$lesson_dir/video.mp4"
~~~

normalize-url преобразует /play/embed/private/<id> в /video/private/<id>
и сохраняет query без перекодирования. Числовой embed оставляет поддерживаемым
embed-адресом. Неподдерживаемый путь требует проверки страницы.
Секретные временные URL после загрузки удалить. Из лога перед отчетом извлечь
только причину ошибки с удаленными ключами доступа.
yt-dlp по умолчанию продолжает загрузку .part. Готовое видео проверять ffprobe;
не считать нулевой/поврежденный файл готовым. Если видео валидно и транскрипт
готов, скачивание и платный вызов пропустить.

## Аудио и ElevenLabs

Сначала создать отдельный stage_dir в work для конкретного видео.
Команды Python ниже выполняются из misc, чтобы работали импорты audio.

~~~bash
mkdir -p "$stage_dir"
cd "$misc_root"
./.venv/bin/python -m audio.extract_audio "$lesson_dir/video.mp4" --format mp3 --output-dir "$stage_dir"
ffmpeg -loglevel error -i "$stage_dir/video.mp3" -ac 1 -ar 16000 -b:a 64k -y "$stage_dir/normalized.mp3"
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$stage_dir/normalized.mp3"
mv "$stage_dir/normalized.mp3" "$stage_dir/video.mp3"
./.venv/bin/python -m audio.transcribe_audio_api "$stage_dir/video.mp3" --provider elevenlabs --language auto --format md --output-dir "$stage_dir" --env-file .configs/.env
~~~

Команда транскрибации разрешена только после согласования стоимости выбранного
пакета либо при наличии соответствующего разрешения в запросе пользователя.
Тариф проверять по официальной странице ElevenLabs перед оценкой, не считать
зашитую в misc оценку фактическим списанием. Указать отсутствие данных о
фактическом списании, если API их не предоставил.

Высококачественный MP3 из extract_audio может быть большим: в реальном пакете
передача 96 МБ не уложилась в сетевой тайм-аут записи. Компактная версия
сохраняет длительность и уменьшает объем передачи; сначала проверить ее
ffprobe, затем заменять промежуточное аудио. Не повторять успешно выполненную
нормализацию. Если загрузка оборвалась до ответа, проверить Request Log
ElevenLabs прежде чем повторять оплачиваемый запрос.

Полученный video.transcript.md проверить и перенести в lesson_dir/transcript.md.
Существующий transcript.md не перезаписывать без запроса. При явно заказанной
повторной обработке сохранять прежний файл до проверки нового. В заголовке
транскрипта допустима исходная метка video.mp3, она обозначает аудиодорожку.

## Локальный Whisper

Использовать turbo. Штатный wrapper misc имеет Windows-путь по умолчанию и
передает language буквально. CLI Whisper отвергает строку None, несмотря на
текст его help. Помощник whisper-run использует build_command из
audio.run_whisper, явно определяет executable и опускает --language при auto.
Сохраняется настройка fp16=False, задаваемая существующим wrapper.

~~~bash
python3 "$skill_helper" whisper-run "$stage_dir/video.mp3" --output-dir "$stage_dir" --misc-root "$misc_root" --whisper-exe /Users/serg/.local/bin/whisper
python3 "$skill_helper" whisper-md "$stage_dir/video.json" --output "$lesson_dir/transcript.md" --source "$lesson_dir/video.mp4" --misc-root "$misc_root" --duration 1598.166667
~~~

Путь executable и duration являются примерами: определить executable через
command -v whisper и длительность текущего видео через ffprobe. Без явного
executable помощник ищет whisper в PATH, игнорируя ошибочный WHISPER_EXE.
JSON является промежуточным: после проверки Markdown удалить созданные этим
запуском JSON и MP3. При ошибке конвертации JSON сохранить в work и повторить
только преобразование, без повторного распознавания.
whisper-md проверяет речь и временные метки и атомарно заменяет выходной файл
только после успешного преобразования через модели/renderer misc.

## Конспект и завершение

summary.md содержит источник (page.md), транскрипт, понятия и определения,
действия с примерами и условиями, метки времени, рекомендации автора.
Просмотреть все modules/**/summary.md, затем полнотекстовым поиском найти
релевантные темы и прочитать связанные конспекты. Ссылки на них относительные
из каталога этого видео. Объяснять связь, не копировать прежние конспекты
и не добавлять их утверждения в описание текущего видео.

В поле состояния оглавления «Готово» означает наличие всех четырех файлов;
index проверяет наличие/непустоту, а агент до этого проверяет качество и
валидность медиа. При ошибке error имеет приоритет, частичные документы
остаются доступными. Оглавление не создает ссылок на отсутствующие документы.

Перед локальным коммитом проверить только свои пути, diff --check, отсутствие
секретов и игнорирование медиа. Коммит включает записи всех успешных этапов
и достоверные статусы ошибок, даже если пакет завершен частично.
Не менять индекс с чужими staged файлами без разрешения.

Проверка помощника:
~~~bash
python3 "$skill_helper" self-test --misc-root "$misc_root"
~~~

Она использует временные файлы и встроенный пример Whisper, не запускает
распознавание, загрузку видео или платный API.
