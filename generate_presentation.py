#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generates an executive-ready, beautifully styled presentation (.pptx)
comparing In-Process OTLP Auto-Instrumentation vs. Node DaemonSet (Grafana Alloy)
based on empirical benchmark and OOM failure data.
"""

import sys
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

# 16:9 Widescreen Dimensions
SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)

# Color Palette (Dark Modern Tech Theme)
BG_COLOR = RGBColor(15, 23, 42)        # #0F172A Deep Navy Slate
CARD_BG = RGBColor(30, 41, 59)         # #1E293B Card Slate
CARD_BORDER = RGBColor(51, 65, 85)     # #334155
CYAN = RGBColor(56, 189, 248)          # #38BDF8 Accent Cyan
EMERALD = RGBColor(16, 185, 129)       # #10B981 Accent Emerald Green (Wins)
ROSE = RGBColor(244, 63, 94)           # #F43F5E Accent Rose / Red (Failure / Overhead)
AMBER = RGBColor(245, 158, 11)         # #F59E0B Accent Amber (Warnings / Highlights)
TEXT_WHITE = RGBColor(248, 250, 252)   # #F8FAFC Primary Header Text
TEXT_LIGHT = RGBColor(226, 232, 240)   # #E2E8F0 Primary Body Text
TEXT_MUTED = RGBColor(148, 163, 184)   # #94A3B8 Secondary Text

FONT_NAME = "Arial"

def create_slide_base(prs, category_tag, slide_title):
    """Creates a standard dark slide with category tag and title."""
    blank_layout = prs.slide_layouts[6] # completely blank layout
    slide = prs.slides.add_slide(blank_layout)

    # Background fill
    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SLIDE_WIDTH, SLIDE_HEIGHT)
    bg.fill.solid()
    bg.fill.fore_color.rgb = BG_COLOR
    bg.line.color.rgb = BG_COLOR

    # Category Tag Box
    tag_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.4), Inches(11.7), Inches(0.4))
    tf_tag = tag_box.text_frame
    tf_tag.word_wrap = True
    tf_tag.margin_left = tf_tag.margin_top = tf_tag.margin_right = tf_tag.margin_bottom = 0
    p_tag = tf_tag.paragraphs[0]
    p_tag.text = category_tag.upper()
    p_tag.font.name = FONT_NAME
    p_tag.font.size = Pt(11)
    p_tag.font.bold = True
    p_tag.font.color.rgb = CYAN

    # Main Slide Title
    title_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.75), Inches(11.7), Inches(0.7))
    tf_title = title_box.text_frame
    tf_title.word_wrap = True
    tf_title.margin_left = tf_title.margin_top = tf_title.margin_right = tf_title.margin_bottom = 0
    p_title = tf_title.paragraphs[0]
    p_title.text = slide_title
    p_title.font.name = FONT_NAME
    p_title.font.size = Pt(24)
    p_title.font.bold = True
    p_title.font.color.rgb = TEXT_WHITE

    # Bottom footer accent line
    line = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.8), Inches(7.1), Inches(11.733), Pt(1.5))
    line.fill.solid()
    line.fill.fore_color.rgb = CARD_BORDER
    line.line.color.rgb = CARD_BORDER

    # Footer note
    footer_box = slide.shapes.add_textbox(Inches(0.8), Inches(7.15), Inches(11.733), Inches(0.3))
    tf_footer = footer_box.text_frame
    tf_footer.margin_left = tf_footer.margin_top = tf_footer.margin_right = tf_footer.margin_bottom = 0
    pf = tf_footer.paragraphs[0]
    pf.text = "Observability Architecture Evaluation • In-Process OTLP vs. Grafana Alloy DaemonSet"
    pf.font.name = FONT_NAME
    pf.font.size = Pt(9)
    pf.font.color.rgb = TEXT_MUTED

    return slide

def add_card(slide, left, top, width, height, title, title_color, bg_color=CARD_BG, border_color=CARD_BORDER):
    """Adds a styled rectangular card container."""
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    card.fill.solid()
    card.fill.fore_color.rgb = bg_color
    card.line.color.rgb = border_color
    card.line.width = Pt(1.5)

    if title:
        title_box = slide.shapes.add_textbox(left + Inches(0.25), top + Inches(0.2), width - Inches(0.5), Inches(0.45))
        tf = title_box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
        p = tf.paragraphs[0]
        p.text = title
        p.font.name = FONT_NAME
        p.font.size = Pt(16)
        p.font.bold = True
        p.font.color.rgb = title_color

    return card

def add_bullet(tf, bold_prefix, text, font_size=12, text_color=TEXT_LIGHT, prefix_color=TEXT_WHITE, space_after=8):
    p = tf.add_paragraph()
    p.space_after = Pt(space_after)
    if bold_prefix:
        r1 = p.add_run()
        r1.text = bold_prefix + ": "
        r1.font.name = FONT_NAME
        r1.font.bold = True
        r1.font.size = Pt(font_size)
        r1.font.color.rgb = prefix_color
    r2 = p.add_run()
    r2.text = text
    r2.font.name = FONT_NAME
    r2.font.size = Pt(font_size)
    r2.font.color.rgb = text_color

# -------------------------------------------------------------
# SLIDE BUILDERS
# -------------------------------------------------------------

def build_slide_1_title(prs):
    """Slide 1: Title Slide"""
    blank_layout = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank_layout)

    bg = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SLIDE_WIDTH, SLIDE_HEIGHT)
    bg.fill.solid()
    bg.fill.fore_color.rgb = BG_COLOR
    bg.line.color.rgb = BG_COLOR

    # Central Box
    box = slide.shapes.add_textbox(Inches(1.2), Inches(1.8), Inches(10.9), Inches(3.8))
    tf = box.text_frame
    tf.word_wrap = True

    p0 = tf.paragraphs[0]
    p0.text = "ארכיטקטורות איסוף לוגים ב-KUBERNETES / OPENSHIFT"
    p0.font.name = FONT_NAME
    p0.font.size = Pt(14)
    p0.font.bold = True
    p0.font.color.rgb = CYAN
    p0.space_after = Pt(14)

    p1 = tf.add_paragraph()
    p1.text = "In-Process OTLP מול Node DaemonSet (Grafana Alloy)"
    p1.font.name = FONT_NAME
    p1.font.size = Pt(36)
    p1.font.bold = True
    p1.font.color.rgb = TEXT_WHITE
    p1.space_after = Pt(14)

    p2 = tf.add_paragraph()
    p2.text = "השוואה ארכיטקטונית מעשית, נתוני ביצועים (CPU/Latency) ולקחי קריסה (OOMKilled Log Loss)"
    p2.font.name = FONT_NAME
    p2.font.size = Pt(18)
    p2.font.color.rgb = TEXT_MUTED
    p2.space_after = Pt(30)

    # 3 Badges
    badges = [
        ("⚡ 31% שיפור ב-Latency", CYAN),
        ("🛡️ 100% שרידות לוגים בקריסות OOM", EMERALD),
        ("📉 25% חיסכון ב-CPU של האפליקציה", AMBER)
    ]
    left_start = Inches(1.2)
    for text, color in badges:
        badge = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left_start, Inches(5.2), Inches(3.4), Inches(0.7))
        badge.fill.solid()
        badge.fill.fore_color.rgb = CARD_BG
        badge.line.color.rgb = color
        badge.line.width = Pt(1.5)
        tf_b = badge.text_frame
        p_b = tf_b.paragraphs[0]
        p_b.alignment = PP_ALIGN.CENTER
        p_b.text = text
        p_b.font.name = FONT_NAME
        p_b.font.bold = True
        p_b.font.size = Pt(12)
        p_b.font.color.rgb = color
        left_start += Inches(3.7)

def build_slide_2_architectures(prs):
    """Slide 2: Two Architectures Detailed"""
    slide = create_slide_base(prs, "סקירה ארכיטקטונית", "שתי הגישות לאיסוף לוגים ב-Kubernetes")

    # Card 1: In-Process OTLP Push
    add_card(slide, Inches(0.8), Inches(1.6), Inches(5.6), Inches(5.1), "שיטה א': In-Process OTLP Direct Push", ROSE)
    box1 = slide.shapes.add_textbox(Inches(1.0), Inches(2.3), Inches(5.2), Inches(4.2))
    tf1 = box1.text_frame
    tf1.word_wrap = True
    add_bullet(tf1, "מנגנון הפעולה", "ספריית ה-SDK (Java Agent, Python, Node.js) תופסת לוגים מתוך ה-Heap של האפליקציה.")
    add_bullet(tf1, "אגירה בזיכרון", "לוגים נשמרים ב-Buffer פנימי (BatchLogRecordProcessor) למשך 1-5 שניות לפני שיגור.")
    add_bullet(tf1, "שיגור ברשת", "ה-SDK מבצע בעצמו סריאליזציה, דחיסת Protobuf ושליחת HTTP/gRPC ישירה ל-Loki או OTel Collector.")
    add_bullet(tf1, "צימוד הדוק", "איסוף הלוגים רץ בתוך תהליך האפליקציה ומתחרה איתה ישירות על זיכרון, תהליכונים ו-CPU.")

    # Card 2: DaemonSet Log Shipper
    add_card(slide, Inches(6.8), Inches(1.6), Inches(5.7), Inches(5.1), "שיטה ב': Node-Level DaemonSet (Grafana Alloy)", EMERALD)
    box2 = slide.shapes.add_textbox(Inches(7.0), Inches(2.3), Inches(5.3), Inches(4.2))
    tf2 = box2.text_frame
    tf2.word_wrap = True
    add_bullet(tf2, "מנגנון הפעולה", "האפליקציה כותבת שורות טקסט פשוטות ל-stdout/stderr דרך צינור ה-Kernel הסטנדרטי.")
    add_bullet(tf2, "כתיבה מיידית לדיסק", "ה-Container Runtime (CRI-O / Containerd) כותב את השורות תוך מיקרו-שניות לקובץ ב-Node.")
    add_bullet(tf2, "קריאה אסינכרונית", "Pod בודד של Alloy על ה-Node קורא את הקבצים (/var/log/pods), מעבד ושולח במקביל ליעדים.")
    add_bullet(tf2, "בידוד מלא", "אפס תקורה על האפליקציה! תקלות רשת או עומסי לוגים מנוהלים עצמאית ב-Alloy ולא פוגעים ב-Pod.")

def build_slide_3_comparison_table(prs):
    """Slide 3: Comprehensive Comparison Table"""
    slide = create_slide_base(prs, "השוואה תכונות", "מטריצת יתרונות וחסרונות (Pros & Cons)")

    # Create Table
    rows = 7
    cols = 3
    left = Inches(0.8)
    top = Inches(1.6)
    width = Inches(11.733)
    height = Inches(5.0)

    table_shape = slide.shapes.add_table(rows, cols, left, top, width, height)
    table = table_shape.table
    table.columns[0].width = Inches(3.0)
    table.columns[1].width = Inches(4.366)
    table.columns[2].width = Inches(4.366)

    headers = ["קריטריון השוואה", "In-Process OTLP (אינסטרומנטציה)", "Node DaemonSet (Grafana Alloy)"]
    for i, h in enumerate(headers):
        cell = table.cell(0, i)
        cell.fill.solid()
        cell.fill.fore_color.rgb = CARD_BG
        p = cell.text_frame.paragraphs[0]
        p.text = h
        p.font.name = FONT_NAME
        p.font.bold = True
        p.font.size = Pt(13)
        p.font.color.rgb = CYAN

    data = [
        ("עומס על האפליקציה (CPU)", "❌ גבוה (+25% תקורה של סריאליזציה ורשת)", "✅ אפסי (האפליקציה רק מדפיסה ל-stdout)"),
        ("השפעה על זמן תגובה (Latency)", "❌ פוגע ב-Latency (10ms+ עיכוב ב-API)", "✅ אפס השפעה על תגובתיות המיקרו-סרביס"),
        ("שרידות בקריסות (OOMKilled)", "❌ איבוד לוגים מלא (ה-Buffer נמחק מיידית)", "✅ 100% שרידות (הלוג נכתב לדיסק ע\"י הקרנל)"),
        ("צריכת זיכרון ב-Pods", "❌ התנפחות Heap עקב תורי זיכרון פנימיים", "✅ צריכת RAM אפסית ויציבה בתוך ה-Pod"),
        ("בידוד תקלות ויעדים (Splunk/Loki)", "❌ נפילת יעד עלולה לנפח את ה-Pod ולגרום OOM", "✅ תור מוגן ב-Alloy בולם זעזועים ללא השפעת פוד"),
        ("קורלציית Traces ללוגים", "✅ קורלציה טבעית בתוך ה-SDK", "✅ מלאה! (TraceID מוזרק ל-stdout ונקרא ב-Alloy)")
    ]

    for row_idx, row_data in enumerate(data, start=1):
        for col_idx, text in enumerate(row_data):
            cell = table.cell(row_idx, col_idx)
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor(22, 30, 46) if row_idx % 2 == 0 else CARD_BG
            p = cell.text_frame.paragraphs[0]
            p.text = text
            p.font.name = FONT_NAME
            p.font.size = Pt(11)
            p.font.color.rgb = TEXT_WHITE if col_idx == 0 else (ROSE if "❌" in text else EMERALD)

def build_slide_4_benchmark(prs):
    """Slide 4: Empirical Benchmark Results"""
    slide = create_slide_base(prs, "בנצ'מרק מעבדה", "מדידות ביצועים: אינסטרומנטציה מול DaemonSet")

    # 3 Metric Summary Cards
    metrics = [
        ("31.2%", "ירידה בזמן תגובה (Latency)", "מ-34.92ms ל-24.01ms תחת עומס יציב", CYAN),
        ("24.5%", "חיסכון ב-CPU באפליקציות", "Node.js: -25.1% | Python: -23.7%", EMERALD),
        ("~115 MB", "צריכת RAM כוללת ל-Alloy", "פוד בודד ל-Node מטפל בכל הפודים ב-7 Threads", AMBER)
    ]

    card_w = Inches(3.64)
    c_left = Inches(0.8)
    for big_num, title, desc, color in metrics:
        add_card(slide, c_left, Inches(1.6), card_w, Inches(1.8), "", color)
        tb = slide.shapes.add_textbox(c_left + Inches(0.2), Inches(1.75), card_w - Inches(0.4), Inches(1.5))
        tf = tb.text_frame
        tf.word_wrap = True

        p1 = tf.paragraphs[0]
        p1.text = big_num
        p1.font.name = FONT_NAME
        p1.font.size = Pt(32)
        p1.font.bold = True
        p1.font.color.rgb = color

        p2 = tf.add_paragraph()
        p2.text = title
        p2.font.name = FONT_NAME
        p2.font.size = Pt(13)
        p2.font.bold = True
        p2.font.color.rgb = TEXT_WHITE

        p3 = tf.add_paragraph()
        p3.text = desc
        p3.font.name = FONT_NAME
        p3.font.size = Pt(10)
        p3.font.color.rgb = TEXT_MUTED

        c_left += Inches(4.04)

    # Detailed Table of Results
    add_card(slide, Inches(0.8), Inches(3.7), Inches(11.733), Inches(3.1), "פירוט תוצאות הבדיקה (40 req/s | 1,601 בקשות)", CYAN)
    tb_table = slide.shapes.add_textbox(Inches(1.0), Inches(4.3), Inches(11.3), Inches(2.3))
    tft = tb_table.text_frame
    tft.word_wrap = True

    add_bullet(tft, "זמן תגובה ממוצע (Latency)", "עם לוגים ב-OTLP: 34.92 ms | ללא לוגים ב-OTLP (stdout בלבד): 24.01 ms (שיפור של 10.91 ms לכל בקשה).", 12, TEXT_LIGHT, CYAN)
    add_bullet(tft, "Frontend (Node.js)", "ירידה בצריכת מעבד מ-296.7m ל-222.2m CPU — חיסכון ישיר של 25.1% מעבד.", 12, TEXT_LIGHT, EMERALD)
    add_bullet(tft, "Backend 1 (Python)", "ירידה בצריכת מעבד מ-279.5m ל-213.1m CPU — חיסכון ישיר של 23.7% מעבד.", 12, TEXT_LIGHT, EMERALD)
    add_bullet(tft, "גידול בזיכרון (Heap Delta)", "באינסטרומנטציה נרשמה צמיחת זיכרון של +26.4 MB לעומת +18.5 MB בלבד ב-stdout (30% פחות לחץ זיכרון).", 12, TEXT_LIGHT, AMBER)
    add_bullet(tft, "תקפות קורלציה", "הסרת ה-OTLP Exporter לא פגעה בקורלציה: Trace ID הוזרק ישירות ל-stdout ונקרא בשלמותו ב-Loki ו-Splunk.", 12, TEXT_LIGHT, CYAN)

def build_slide_5_oom_test(prs):
    """Slide 5: Live OOM / Container Kill Proof"""
    slide = create_slide_base(prs, "מבחן קריסה ואמינות", "ניסוי חבלה: איבוד לוגים קריטי בקריסת OOMKilled")

    # Top Alert
    alert = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(1.6), Inches(11.733), Inches(1.1))
    alert.fill.solid()
    alert.fill.fore_color.rgb = RGBColor(40, 16, 25)
    alert.line.color.rgb = ROSE
    alert.line.width = Pt(1.5)
    tfa = alert.text_frame
    tfa.margin_left = Inches(0.25)
    pa = tfa.paragraphs[0]
    pa.text = "🚨 תרחיש כשל: קריסת זיכרון פתאומית (Kernel OOMKilled / Exit Code 137)"
    pa.font.name = FONT_NAME
    pa.font.size = Pt(14)
    pa.font.bold = True
    pa.font.color.rgb = ROSE
    pa2 = tfa.add_paragraph()
    pa2.text = "כאשר פוד חורג ממגבלת הזיכרון, הקרנל הורג אותו מיידית ב-SIGKILL ללא הפעלת Shutdown Hooks. כל מידע ב-Heap נמחק."
    pa2.font.name = FONT_NAME
    pa2.font.size = Pt(11)
    pa2.font.color.rgb = TEXT_LIGHT

    # Card 1: Pipeline A Failure
    add_card(slide, Inches(0.8), Inches(2.9), Inches(5.6), Inches(3.9), "Pipeline A: In-Process OTLP Direct Push", ROSE)
    box1 = slide.shapes.add_textbox(Inches(1.0), Inches(3.5), Inches(5.2), Inches(3.1))
    tf1 = box1.text_frame
    tf1.word_wrap = True
    add_bullet(tf1, "תוצאת שאילתת Loki", "התקבלו 2 לוגים בלבד מתוך 6!", 12, ROSE, TEXT_WHITE)
    add_bullet(tf1, "לוגים שהגיעו", "[PHASE-1-ONLINE] פוד אותחל ועובד תקין.", 11, TEXT_MUTED)
    add_bullet(tf1, "לוגי הקריסה (Crash Logs)", "❌ 100% איבוד מידע! 0 מתוך 3 לוגי קריסה הגיעו ליעד!", 12, ROSE, ROSE)
    add_bullet(tf1, "מה הושמד בזיכרון?", "'Database timeout', 'Exception: Out of memory', 'FATAL: Process killed abruptly'.", 11, TEXT_MUTED)
    add_bullet(tf1, "משמעות מבצעית", "באירוע אמת מהנדס ה-SRE רואה פוד מת, אך אין לו אף שורת לוג שמסבירה מדוע הוא קרס!", 12, TEXT_LIGHT, AMBER)

    # Card 2: Pipeline B Success
    add_card(slide, Inches(6.8), Inches(2.9), Inches(5.7), Inches(3.9), "Pipeline B: Grafana Alloy DaemonSet", EMERALD)
    box2 = slide.shapes.add_textbox(Inches(7.0), Inches(3.5), Inches(5.3), Inches(3.1))
    tf2 = box2.text_frame
    tf2.word_wrap = True
    add_bullet(tf2, "תוצאת שאילתת Loki", "התקבלו 6 מתוך 6 לוגים במלואם (100% שרידות)!", 12, EMERALD, TEXT_WHITE)
    add_bullet(tf2, "לוגים שהגיעו", "כל הלוגים: שלב עבודה, זמני תגובה, ולוגי הקריסה המלאים.", 11, TEXT_MUTED)
    add_bullet(tf2, "לוגי הקריסה (Crash Logs)", "✅ כל לוגי ה-Exception וה-Stacktrace נקלטו ב-Loki וב-Splunk.", 12, EMERALD, EMERALD)
    add_bullet(tf2, "מדוע זה הצליח?", "האפליקציה כתבה ל-stdout; ה-Runtime כתב לדיסק מיקרו-שניות לפני שה-SIGKILL נחת.", 12, TEXT_LIGHT, TEXT_WHITE)
    add_bullet(tf2, "משמעות מבצעית", "שרידות מוחלטת של יומני החקירה ל-Post-Mortem ללא שום תלות במצב הפוד.", 12, TEXT_LIGHT, EMERALD)

def build_slide_6_failure_isolation(prs):
    """Slide 6: Failure Isolation & Destination Downtime"""
    slide = create_slide_base(prs, "חוסן מערכתי", "התמודדות עם קריסת יעדים (Splunk / Loki Down)")

    add_card(slide, Inches(0.8), Inches(1.6), Inches(5.6), Inches(5.1), "התנהגות באינסטרומנטציה ישירה", ROSE)
    box1 = slide.shapes.add_textbox(Inches(1.0), Inches(2.3), Inches(5.2), Inches(4.2))
    tf1 = box1.text_frame
    tf1.word_wrap = True
    add_bullet(tf1, "הצפת זיכרון בפוד", "כאשר יעד הלוגים (Splunk/Loki) איטי או נפל, ה-Buffer הפנימי של ה-SDK נסתם.")
    add_bullet(tf1, "סכנת קריסה שרשרתית", "הזיכרון באפליקציה מטפס במהירות. פודים מתחילים לחרוג מ-limits וסופגים OOMKilled!")
    add_bullet(tf1, "חוסר בידוד בין יעדים", "אם שולחים לשני יעדים ויעד אחד איטי, ה-Thread של האפליקציה נתקע ומאט את כל הבקשות.")
    add_bullet(tf1, "איבוד מידע בדרופ", "כשהתור בפוד מלא, ה-SDK זורק לוגים ללא בקרה או מעקב של הארגון.")

    add_card(slide, Inches(6.8), Inches(1.6), Inches(5.7), Inches(5.1), "התנהגות ב-Alloy DaemonSet (נבדק בעומס)", EMERALD)
    box2 = slide.shapes.add_textbox(Inches(7.0), Inches(2.3), Inches(5.3), Inches(4.2))
    tf2 = box2.text_frame
    tf2.word_wrap = True
    add_bullet(tf2, "בידוד תקלות מלא (Isolation)", "בניסוי הפלת Splunk: Loki המשיך לקבל 9,200 לוגים בזמן אמת ללא שום עיכוב!")
    add_bullet(tf2, "תור זיכרון מוגן ומבוקר", "ל-Alloy יש תור חסום (queue_size=200). בשיא העומס הזיכרון נבלם ב-337MB ללא קריסת Node.")
    add_bullet(tf2, "ריקון מהיר בחזרה (Flush)", "ברגע ש-Splunk הוחזר לפעולה, Alloy פרק מיד 84,969 אירועים שהמתינו בתור.")
    add_bullet(tf2, "אפס השפעה על ה-Microservices", "האפליקציות המשיכו לרוץ ב-100% ביצועים — הקריסה של יעד הלוגים הייתה שקופה להן לחלוטין.")

def build_slide_7_recommendation(prs):
    """Slide 7: Final Architecture Recommendation"""
    slide = create_slide_base(prs, "המלצה ארכיטקטונית", "המודל ההיברידי: The Best of Both Worlds")

    # 3 Pillars
    pillars = [
        ("1. אינסטרומנטציה: Traces בלבד", "שימוש ב-OTel Operator עבור W3C Context Propagation ומדידת Spans/Metrics. ביטול מוחלט של ה-OTLP Log Exporter.", CYAN),
        ("2. לוגים: כתיבה טבעית ל-stdout", "אפליקציות פולטות לוגים רגילים. ה-SDK מזריק TraceID/SpanID אוטומטית לשורת הלוג ב-stdout ללא עלות רשת.", EMERALD),
        ("3. איסוף לוגים: DaemonSet (Alloy)", "Alloy אוסף את הלוגים מה-Node, מחלץ את ה-Trace ID מהטקסט, ומנתב במקביל ל-Loki ול-Splunk HEC.", AMBER)
    ]

    p_top = Inches(1.6)
    for title, desc, col in pillars:
        add_card(slide, Inches(0.8), p_top, Inches(11.733), Inches(1.3), title, col)
        box = slide.shapes.add_textbox(Inches(1.0), p_top + Inches(0.55), Inches(11.3), Inches(0.65))
        tf = box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = desc
        p.font.name = FONT_NAME
        p.font.size = Pt(13)
        p.font.color.rgb = TEXT_LIGHT
        p_top += Inches(1.5)

    # Bottom Summary Box
    bot_card = add_card(slide, Inches(0.8), Inches(6.1), Inches(11.733), Inches(0.85), "", CYAN, RGBColor(22, 30, 46))
    bb = slide.shapes.add_textbox(Inches(1.0), Inches(6.15), Inches(11.3), Inches(0.75))
    tfb = bb.text_frame
    pb = tfb.paragraphs[0]
    pb.alignment = PP_ALIGN.CENTER
    pb.text = "🎯 התוצאה לארגון: 100% שרידות לוגים בקריסות • 25% חיסכון ב-CPU • 31% שיפור ב-Latency • קורלציה מושלמת בין Logs ל-Traces"
    pb.font.name = FONT_NAME
    pb.font.size = Pt(12)
    pb.font.bold = True
    pb.font.color.rgb = EMERALD

# -------------------------------------------------------------
# MAIN
# -------------------------------------------------------------

def main():
    output_path = "/Users/ronen/Documents/observability-poc/log_collection_architecture_presentation.pptx"
    print(f"Generating presentation at: {output_path}")

    prs = Presentation()
    prs.slide_width = SLIDE_WIDTH
    prs.slide_height = SLIDE_HEIGHT

    build_slide_1_title(prs)
    build_slide_2_architectures(prs)
    build_slide_3_comparison_table(prs)
    build_slide_4_benchmark(prs)
    build_slide_5_oom_test(prs)
    build_slide_6_failure_isolation(prs)
    build_slide_7_recommendation(prs)

    prs.save(output_path)
    print("✅ Presentation generated successfully!")

if __name__ == "__main__":
    main()
