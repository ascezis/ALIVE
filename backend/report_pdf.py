"""Print-ready ALIVE diary reports."""

from datetime import timedelta
from html import escape
from io import BytesIO
from math import ceil
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table


FONT = "ReportSans"
BOLD = "ReportSansBold"
FONTS = Path(__file__).with_name("report_fonts")
pdfmetrics.registerFont(TTFont(FONT, FONTS / "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont(BOLD, FONTS / "DejaVuSans-Bold.ttf"))

INK = colors.HexColor("#202833")
MUTED = colors.HexColor("#515e6b")
ACCENT = colors.HexColor("#234b65")
RULE = colors.HexColor("#d8dfe4")
TINT = colors.HexColor("#f2f5f7")
MARGIN = 43
WIDTH = A4[0] - 2 * MARGIN - 12


def style(name, size, leading, *, bold=False, color=INK, before=0, after=0, keep=False):
    return ParagraphStyle(
        name, fontName=BOLD if bold else FONT, fontSize=size, leading=leading,
        textColor=color, spaceBefore=before, spaceAfter=after, keepWithNext=keep, splitLongWords=True,
    )


EYEBROW = style("Eyebrow", 9, 14, bold=True, color=ACCENT, after=5)
TITLE = style("Title", 26, 32, bold=True, after=8)
SUBTITLE = style("Subtitle", 10, 15, color=MUTED, after=15)
DAY = style("Day", 13, 17, bold=True, before=7, after=3, keep=True)
BODY = style("Body", 10, 15, after=4)
SMALL = style("Small", 9, 13, color=MUTED, after=7)
VALUE = style("Value", 17, 23, bold=True)
LABEL = style("Label", 8, 12, color=MUTED)


def datestr(day):
    return day.strftime("%d.%m.%Y")


def text(value):
    return escape(value).replace("\n", "<br/>")


class Timeline(Flowable):
    def __init__(self, start, end, title, observations, *, ticks=None, activity_days=(), chart_height=141):
        super().__init__()
        self.start = start
        self.days = (end - start).days
        self.title = title
        self.observations = observations
        self.ticks = ticks
        self.activity_days = activity_days
        self.width = WIDTH
        self.height = chart_height if ticks else 69

    def draw(self):
        c = self.canv
        c.setFillColor(INK)
        c.setFont(BOLD, 11)
        c.drawString(0, self.height - 12, self.title)
        left, right, bottom, top = 35, self.width - 23, 27, self.height - 30

        def x_at(day_offset):
            if self.days == 0:
                return (left + right) / 2
            return left + day_offset * (right - left) / self.days

        c.setFont(FONT, 7.5)
        c.setFillColor(MUTED)
        c.setStrokeColor(RULE)
        if self.ticks:
            maximum = self.ticks[-1]
            for tick in self.ticks:
                y = bottom + tick * (top - bottom) / maximum
                c.drawRightString(left - 7, y - 2.5, str(tick))
                c.line(left, y, right, y)
            c.setLineWidth(.7)
            c.setDash(1, 2)
            for day in self.activity_days:
                x = x_at((day - self.start).days)
                c.line(x, bottom, x, top)
            c.setDash()
        else:
            c.line(left, bottom, right, bottom)

        count = min(self.days, 5)
        offsets = [round(self.days * index / count) for index in range(count + 1)] if count else [0]
        for offset in offsets:
            label = (self.start + timedelta(days=offset)).strftime("%d.%m")
            c.drawCentredString(x_at(offset), 9, label)

        if not self.observations:
            c.setFont(FONT, 9)
            c.drawCentredString((left + right) / 2, (bottom + top) / 2 + (0 if self.ticks else 3), "Нет записей")
            return

        c.setFillColor(ACCENT)
        c.setStrokeColor(ACCENT)
        c.setLineWidth(1.15)
        previous = None
        for day, value in self.observations:
            offset = (day - self.start).days
            x = x_at(offset)
            if self.ticks:
                y = bottom + value * (top - bottom) / maximum
                if previous:
                    if offset > previous[0] + 1:
                        c.setDash(3, 2)
                    c.line(previous[1], previous[2], x, y)
                    c.setDash()
                c.circle(x, y, 2.4, stroke=0, fill=1)
                previous = (offset, x, y)
            else:
                c.line(x, bottom, x, bottom + 7)
                c.circle(x, bottom + 8, 2, stroke=0, fill=1)


def metrics(pain_days, stiffness_days, fatigue_days, sessions, span):
    entries = [
        (f"{pain_days} из {span}", "Дней с оценкой боли"),
        (f"{stiffness_days} из {span}", "Дней с отметкой скованности"),
    ]
    if fatigue_days:
        entries.append((f"{fatigue_days} из {span}", "Дней с оценкой утомляемости"))
    entries.append((str(sessions), "Занятий ЛФК"))
    return Table(
        [[Paragraph(number, VALUE) for number, _ in entries], [Paragraph(label, LABEL) for _, label in entries]],
        colWidths=[WIDTH / len(entries)] * len(entries),
        style=[
            ("BACKGROUND", (0, 0), (-1, -1), TINT),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, 0), 9),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
        ],
    )


def workout_line(workout):
    title = workout.title or ("Занятие по видео" if workout.mode == "video" else "ЛФК")
    parts = [title]
    if workout.duration is not None:
        minutes, seconds = divmod(workout.duration, 60)
        parts.append(f"{minutes} мин {seconds:02d} с")
    if workout.results is not None:
        completed = workout.results.count("done")
        parts.append(f"выполнено {completed} из {len(workout.results)}")
    return " · ".join(parts)


def footer(canvas, document):
    canvas.setStrokeColor(RULE)
    canvas.line(MARGIN + 6, 47, A4[0] - MARGIN - 6, 47)
    canvas.setFillColor(MUTED)
    canvas.setFont(FONT, 8)
    canvas.drawString(MARGIN + 6, 33, "ALIVE · Данные дневника пациента")
    canvas.drawRightString(A4[0] - MARGIN - 6, 33, f"Страница {document.page}")


def build_report(start, end, entries):
    """Generate a PDF from dated diary entries sorted in calendar order."""
    pain = [(day, entry.pain) for day, entry in entries if entry.pain is not None]
    stiffness = [(day, entry.stiffness) for day, entry in entries if entry.stiffness is not None]
    fatigue = [(day, entry.fatigue) for day, entry in entries if entry.fatigue is not None]
    activity = [(day, len(entry.workouts)) for day, entry in entries if entry.workouts]
    activity_days = [day for day, _ in activity]
    stiffness_step = max(15, 15 * ceil(max((value for _, value in stiffness), default=0) / 60))
    output = BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=45, bottomMargin=62,
        title="Дневник самочувствия для ревматолога", author="ALIVE",
    )
    period = f"{datestr(start)} - {datestr(end)}"
    chart_height = 111 if fatigue else 141
    story = [
        Paragraph("ОТЧЁТ ДЛЯ РЕВМАТОЛОГА", EYEBROW),
        Paragraph("Дневник самочувствия", TITLE),
        Paragraph(period, SUBTITLE),
        metrics(len(pain), len(stiffness), len(fatigue), sum(count for _, count in activity), (end - start).days + 1),
        Spacer(1, 16),
        Timeline(start, end, "Боль, 0-10", pain, ticks=range(0, 11, 2),
                 activity_days=activity_days, chart_height=chart_height),
        Spacer(1, 8),
        Timeline(start, end, "Утренняя скованность, мин", stiffness,
                 ticks=range(0, 5 * stiffness_step, stiffness_step), activity_days=activity_days, chart_height=chart_height),
    ]
    if fatigue:
        story.extend([
            Spacer(1, 8),
            Timeline(start, end, "Утомляемость, 0-10", fatigue, ticks=range(0, 11, 2),
                     activity_days=activity_days, chart_height=chart_height),
        ])
    story.extend([
        Spacer(1, 8),
        Timeline(start, end, "Дни с занятиями ЛФК", activity),
        Paragraph(
            "Точки — фактические записи. Сплошная линия соединяет записи за соседние дни. "
            "Пунктир означает, что между точками есть дни без записи. Вертикальные линии отмечают дни ЛФК.",
            SMALL,
        ),
    ])
    if entries:
        story.extend([
            PageBreak(),
            Paragraph("ПРИЛОЖЕНИЕ", EYEBROW),
            Paragraph("Записи по дням", TITLE),
            Paragraph(period, SUBTITLE),
        ])
    for day, entry in reversed(entries):
        story.append(Paragraph(datestr(day), DAY))
        observations = []
        if entry.pain is not None:
            observations.append(f"Боль {entry.pain}/10")
        if entry.stiffness is not None:
            observations.append(f"Утренняя скованность {entry.stiffness} мин")
        if entry.fatigue is not None:
            observations.append(f"Утомляемость {entry.fatigue}/10")
        story.append(Paragraph(" · ".join(observations) or "Самочувствие не отмечено", SMALL))
        for workout in entry.workouts:
            story.append(Paragraph(text(workout_line(workout)), BODY))
            if workout.note:
                story.append(Paragraph(f"После занятия: {text(workout.note)}", BODY))
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
