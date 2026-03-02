"""
Расписание для групп 2507а1 и 2507а2 с сайта table-ci.nsu.ru.

Бот делает скриншот таблицы расписания (CSS‑селектор `table.schedule-table`)
через Playwright. Если с этим что‑то идёт не так, есть текстовый фолбэк.
"""

import io
import logging
import asyncio

import requests
from bs4 import BeautifulSoup

try:
    import pdfplumber
except ImportError:  # pdfplumber не установлен – используем текстовый фолбэк
    pdfplumber = None

try:
    from playwright.async_api import async_playwright
except ImportError:  # Playwright не установлен
    async_playwright = None

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # Pillow не установлен – поддержим graceful fallback
    Image = None
    ImageDraw = None
    ImageFont = None

logger = logging.getLogger(__name__)

# Страницы расписания для подгрупп
GROUP1_URL = "https://table-ci.nsu.ru/classes/%D0%922507%D0%B01"  # В2507а1
GROUP2_URL = "https://table-ci.nsu.ru/classes/%D0%922507%D0%B02"  # В2507а2

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ru-RU,ru;q=0.9",
}


def _get_group_schedule_from_site(url: str, title: str) -> str:
    """Загружает и форматирует расписание одной подгруппы с table-ci.nsu.ru.

    Для фолбэка используем обычный requests + BeautifulSoup (без JS).
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        logger.error(f"Ошибка текстовой загрузки расписания: {e}")
        return f"{title}\nНе удалось загрузить расписание на сайте."

    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.schedule-table")
    if not table:
        logger.error("На странице не найдена таблица schedule-table для текстового фолбэка.")
        return f"{title}\nНе удалось найти таблицу расписания на сайте."

    text = table.get_text("\n", strip=True)
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    return f"{title}\n\n" + "\n".join(lines)


async def _screenshot_page_async(url: str) -> bytes:
    """Делает скриншот только таблицы расписания (`table.schedule-table`) и возвращает PNG bytes."""
    if async_playwright is None:
        raise RuntimeError("Playwright не установлен. Установи пакет 'playwright' и запусти 'playwright install'.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        await page.goto(url, wait_until="networkidle")
        # Ждём, пока появится таблица расписания
        table = await page.wait_for_selector("table.schedule-table", timeout=10000)
        # Небольшая пауза, чтобы содержимое точно успело дорисоваться
        await page.wait_for_timeout(500)
        # Скриншот только нужного элемента
        png_bytes = await table.screenshot(type="png")
        await browser.close()
        return png_bytes


def screenshot_page(url: str) -> bytes | None:
    """Синхронная обёртка над скриншотом страницы."""
    try:
        return asyncio.run(_screenshot_page_async(url))
    except Exception as e:
        logger.error(f"Ошибка скриншота через Playwright: {e}")
        return None


def _header_group_match(s: str) -> bool:
    """Проверяет, что в заголовке столбца указана именно группа 2507а1 или 2507а2."""
    if not s:
        return False
    t = str(s).strip().lower()
    # убираем пробелы и приводим кириллицу 'а' к латинице
    t = t.replace(" ", "")
    t = t.replace("а", "a")
    # ожидаем варианты вида 2507a1, 2507a2
    return t == "2507a1" or t == "2507a2"


def _group_match(s: str) -> bool:
    """Проверяет, что в произвольной строке упомянута наша группа 2507а*."""
    if not s:
        return False
    t = str(s).strip().lower()
    # убираем пробелы и приводим кириллицу 'а' к латинице
    t = t.replace(" ", "")
    t = t.replace("а", "a")
    # достаточно, чтобы встречалось 2507a или конкретные подгруппы
    return ("2507a" in t) or ("2507a1" in t) or ("2507a2" in t)


def _extract_group_from_pdf(pdf_bytes: bytes) -> str:
    """Извлекает из PDF только расписание группы 2507а.

    Логика:
    1. Ищем строку‑заголовок таблицы, где перечислены группы (2507а1, 2507а2, ...).
    2. Запоминаем индексы столбцов для группы 2507а*.
    3. Для всех следующих строк берём:
       - первые 1–2 столбца (обычно номер пары / время),
       - только столбцы нашей группы.
    """
    lines: list[str] = []

    if pdfplumber is None:
        logger.error("Модуль 'pdfplumber' не установлен — возвращаем пустой результат для PDF.")
        return ""

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if not table:
                        continue

                    header_idx = None
                    group_cols: list[int] = []
                    meta_cols: list[int] = []

                    # 1. Находим строку‑заголовок с группами
                    for idx, row in enumerate(table):
                        row_str = [str(c or "").strip() for c in row]
                        # В заголовке ищем только 2507а1 и 2507а2
                        if any(_header_group_match(cell) for cell in row_str):
                            header_idx = idx
                            # Столбцы с 2507а* (может быть несколько, но нам нужен только первый)
                            group_cols = [
                                j
                                for j, cell in enumerate(row_str)
                                if _header_group_match(cell)
                            ]
                            # Первые столбцы — номер пары / время (эвристика)
                            if len(row_str) >= 2:
                                meta_cols = [0, 1]
                            elif len(row_str) == 1:
                                meta_cols = [0]
                            else:
                                meta_cols = []

                            # Строка заголовка для вывода — берём только первый столбец нашей группы
                            header_cells = []
                            main_group_col = group_cols[0]
                            for j in meta_cols + [main_group_col]:
                                if j < len(row_str) and row_str[j]:
                                    header_cells.append(row_str[j])
                            if header_cells:
                                lines.append(" | ".join(header_cells))
                            break

                    if header_idx is None or not group_cols:
                        # В этой таблице нет нужной группы
                        continue

                    # 2. Идём по строкам ниже заголовка и берём только первый столбец нашей группы.
                    if group_cols:
                        main_group_col = group_cols[0]
                    else:
                        main_group_col = 0

                    current_day: str | None = None
                    day_names = {
                        "ПОНЕДЕЛЬНИК",
                        "ВТОРНИК",
                        "СРЕДА",
                        "ЧЕТВЕРГ",
                        "ПЯТНИЦА",
                        "СУББОТА",
                        "ВОСКРЕСЕНЬЕ",
                        "ВОСКРЕСЕНИЕ",
                    }

                    for row in table[header_idx + 1 :]:
                        row_str = [str(c or "").strip() for c in row]
                        if all(not c for c in row_str):
                            continue

                        # Обновляем текущий день, если встретили его название
                        for cell in row_str:
                            if cell and cell.upper() in day_names:
                                current_day = cell.upper()
                                break

                        # Пропускаем строку, если во всех столбцах нашей группы пусто
                        if all(
                            (j >= len(row_str)) or (not row_str[j]) for j in group_cols
                        ):
                            continue

                        cells_out: list[str] = []
                        # Номер пары / время
                        for j in meta_cols:
                            if j < len(row_str) and row_str[j]:
                                cells_out.append(row_str[j])

                        # Во всех днях берём только первый (основной) столбец нашей группы.
                        if main_group_col < len(row_str) and row_str[main_group_col]:
                            cells_out.append(row_str[main_group_col])

                        if cells_out:
                            lines.append(" | ".join(cells_out))

                    if lines:
                        lines.append("")  # разделитель между таблицами

    except Exception as e:
        logger.error(f"Ошибка разбора PDF: {e}")
        return f"Ошибка чтения PDF: {e}"

    # Фолбэк: если по таблицам ничего не нашли — простой текст
    if not lines and pdfplumber is not None:
        try:
            text_lines: list[str] = []
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if not text:
                        continue
                    for line in text.splitlines():
                        line = line.strip()
                        if _group_match(line):
                            text_lines.append(line)
            if text_lines:
                lines.extend(text_lines)
        except Exception as e:
            logger.error(f"Ошибка резервного чтения PDF: {e}")

    return "\n".join(lines).strip() if lines else ""


def get_schedule(url: str | None = None) -> str:
    """Берёт расписание сразу двух подгрупп 2507а1 и 2507а2 с table-ci.nsu.ru."""
    parts: list[str] = []
    parts.append(_get_group_schedule_from_site(GROUP1_URL, "📅 <b>Расписание группы 2507а1</b>"))
    parts.append("")  # пустая строка‑разделитель
    parts.append(_get_group_schedule_from_site(GROUP2_URL, "📅 <b>Расписание группы 2507а2</b>"))
    text = "\n".join(parts)
    # Ограничиваем до 4000 символов для Telegram
    return text[:4000]


def _render_schedule_image(text: str) -> bytes:
    """Рисует PNG‑картинку с переданным текстом расписания и возвращает bytes.

    Требуется установленный Pillow (`pip install pillow`).
    """
    if Image is None or ImageDraw is None or ImageFont is None:
        raise RuntimeError(
            "Для вывода расписания картинкой нужен пакет 'Pillow'. "
            "Установи его: pip install pillow"
        )

    # Подготовка текста
    lines = text.splitlines() or [""]

    # Базовые параметры
    padding_x = 30
    padding_y = 25
    bg_color = (255, 255, 255)
    text_color = (0, 0, 0)

    # Шрифт: пытаемся взять системный, иначе дефолтный
    try:
        # На Windows обычно есть arial.ttf
        font = ImageFont.truetype("arial.ttf", 18)
    except Exception:
        font = ImageFont.load_default()

    # Оценка размеров текста
    dummy_img = Image.new("RGB", (1, 1), bg_color)
    draw = ImageDraw.Draw(dummy_img)

    max_width = 0
    line_heights: list[int] = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        max_width = max(max_width, w)
        line_heights.append(h)

    line_height = (max(line_heights) if line_heights else 18) + 6
    img_width = max_width + padding_x * 2
    img_height = line_height * len(lines) + padding_y * 2

    # Создаём финальное изображение
    img = Image.new("RGB", (img_width, img_height), bg_color)
    draw = ImageDraw.Draw(img)

    y = padding_y
    for line in lines:
        draw.text((padding_x, y), line, font=font, fill=text_color)
        y += line_height

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_schedule_image_bytes(url: str | None = None) -> bytes | str:
    """Возвращает PNG с расписанием как bytes.

    Сейчас основная логика — сделать скриншоты страниц table-ci.nsu.ru
    для подгрупп 2507а1 и 2507а2 и при необходимости склеить их.

    Если Playwright не сработает, есть фолбэк на старый текстовый вариант.
    """
    # 1. Пытаемся сделать скриншоты страниц
    img1 = screenshot_page(GROUP1_URL)
    img2 = screenshot_page(GROUP2_URL)

    if img1 and img2 and Image is not None:
        # Склеиваем две PNG по вертикали
        try:
            i1 = Image.open(io.BytesIO(img1))
            i2 = Image.open(io.BytesIO(img2))
            width = max(i1.width, i2.width)
            height = i1.height + i2.height
            combined = Image.new("RGB", (width, height), (255, 255, 255))
            combined.paste(i1, (0, 0))
            combined.paste(i2, (0, i1.height))
            buf = io.BytesIO()
            combined.save(buf, format="PNG")
            return buf.getvalue()
        except Exception as e:
            logger.error(f"Ошибка склейки изображений расписания: {e}")
            # если что-то пошло не так — просто вернём первый успешный скрин
            return img1

    if img1:
        return img1
    if img2:
        return img2

    # 2. Фолбэк: если скриншоты не удались, работаем по старой схеме (текст → картинка/текст)
    text = get_schedule(url)
    if not text:
        return "Не удалось получить расписание ни через скриншот, ни текстом."

    try:
        return _render_schedule_image(text)
    except Exception as e:
        logger.error(f"Не удалось нарисовать картинку с текстовым расписанием: {e}")
        return text
