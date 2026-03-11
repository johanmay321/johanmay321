"""
build_pptx.py — generates slide_deck.pptx
Run: pip install python-pptx && python build_pptx.py
"""

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt
import pptx.oxml.ns as nsmap
from lxml import etree

# ── Palette ────────────────────────────────────────────────
BG        = RGBColor(0x0f, 0x17, 0x2a)
WHITE     = RGBColor(0xf1, 0xf5, 0xf9)
MUTED     = RGBColor(0x94, 0xa3, 0xb8)
DIM       = RGBColor(0x47, 0x55, 0x69)
BLUE      = RGBColor(0x60, 0xa5, 0xfa)
GREEN     = RGBColor(0x34, 0xd3, 0x99)
PURPLE    = RGBColor(0xc0, 0x84, 0xfc)
AMBER     = RGBColor(0xfb, 0xbf, 0x24)
CARD_BG   = RGBColor(0x1e, 0x29, 0x3b)

W = Inches(13.33)   # widescreen 16:9
H = Inches(7.5)

# ── Helpers ────────────────────────────────────────────────

def new_prs():
    prs = Presentation()
    prs.slide_width  = W
    prs.slide_height = H
    return prs

def blank_slide(prs):
    layout = prs.slide_layouts[6]   # completely blank
    return prs.slides.add_slide(layout)

def set_bg(slide, color: RGBColor):
    bg = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = color

def add_textbox(slide, text, left, top, width, height,
                font_size=18, bold=False, color=WHITE,
                align=PP_ALIGN.LEFT, italic=False):
    txBox = slide.shapes.add_textbox(left, top, width, height)
    tf    = txBox.text_frame
    tf.word_wrap = True
    p  = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size   = Pt(font_size)
    run.font.bold   = bold
    run.font.italic = italic
    run.font.color.rgb = color
    return txBox

def add_rect(slide, left, top, width, height, fill_color, line_color=None):
    shape = slide.shapes.add_shape(
        1,  # MSO_SHAPE_TYPE.RECTANGLE
        left, top, width, height
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_color
    if line_color:
        shape.line.color.rgb = line_color
        shape.line.width = Pt(0.5)
    else:
        shape.line.fill.background()
    return shape

def add_card(slide, left, top, width, height, label, value, sub,
             value_color=BLUE):
    add_rect(slide, left, top, width, height, CARD_BG, RGBColor(0x2d, 0x3f, 0x55))
    pad = Inches(0.2)
    # label
    add_textbox(slide, label,
                left + pad, top + Inches(0.15),
                width - pad*2, Inches(0.35),
                font_size=9, color=MUTED, align=PP_ALIGN.CENTER)
    # value
    add_textbox(slide, value,
                left + pad, top + Inches(0.5),
                width - pad*2, Inches(0.7),
                font_size=26, bold=True, color=value_color, align=PP_ALIGN.CENTER)
    # sub
    add_textbox(slide, sub,
                left + pad, top + Inches(1.2),
                width - pad*2, Inches(0.3),
                font_size=9, color=DIM, align=PP_ALIGN.CENTER)

def eyebrow(slide, text):
    add_textbox(slide, text.upper(),
                Inches(0), Inches(0.5), W, Inches(0.4),
                font_size=10, color=MUTED, align=PP_ALIGN.CENTER)

def heading(slide, text, top=Inches(1.0)):
    add_textbox(slide, text,
                Inches(0.5), top, W - Inches(1), Inches(0.9),
                font_size=34, bold=True, color=WHITE, align=PP_ALIGN.CENTER)

def divider(slide, color=BLUE, top=Inches(2.0)):
    add_rect(slide, W/2 - Inches(0.5), top, Inches(1), Inches(0.05), color)

def add_bar(slide, label, value_text, pct, color, top):
    """Horizontal bar row."""
    lw = Inches(2.2)
    bx = Inches(2.5)
    bw = Inches(9.5)
    bh = Inches(0.42)

    add_textbox(slide, label,
                Inches(0.3), top, lw, bh,
                font_size=11, color=MUTED, align=PP_ALIGN.RIGHT)
    # track
    add_rect(slide, bx, top, bw, bh, RGBColor(0x1e, 0x29, 0x3b))
    # fill
    fill_w = int(bw * pct)
    add_rect(slide, bx, top, fill_w, bh, color)
    # label on bar
    add_textbox(slide, value_text,
                bx + Inches(0.1), top, Inches(1.2), bh,
                font_size=11, bold=True, color=WHITE)

def add_table_row(slide, cells, tops, col_xs, col_ws, row_h,
                  colors=None, bold=False, bg=CARD_BG):
    for i, (text, x, w) in enumerate(zip(cells, col_xs, col_ws)):
        add_rect(slide, x, tops, w - Inches(0.04), row_h, bg,
                 RGBColor(0x2d, 0x3f, 0x55))
        c = colors[i] if colors else WHITE
        add_textbox(slide, text,
                    x + Inches(0.12), tops + Inches(0.05),
                    w - Inches(0.2), row_h - Inches(0.1),
                    font_size=12, bold=bold, color=c,
                    align=PP_ALIGN.CENTER if i > 0 else PP_ALIGN.LEFT)

# ── Build slides ───────────────────────────────────────────

def slide1_title(prs):
    s = blank_slide(prs)
    set_bg(s, BG)
    eyebrow(s, "Glassdoor Salary Analysis · 2024")
    # big title with two-color effect (two stacked textboxes)
    add_textbox(s, "Veterinarian Salaries",
                Inches(0.5), Inches(1.2), W - Inches(1), Inches(0.9),
                font_size=48, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    # line 2
    tb = slide1_colored_line(s)
    add_textbox(s, "A data-driven comparison of veterinarian compensation across two major\nU.S. metro markets, sourced from self-reported Glassdoor salary records.",
                Inches(1.5), Inches(3.6), W - Inches(3), Inches(1.2),
                font_size=14, color=MUTED, align=PP_ALIGN.CENTER)
    add_textbox(s, "Source: Glassdoor · Scraped via automated browser extraction",
                Inches(0.5), H - Inches(0.6), W - Inches(1), Inches(0.3),
                font_size=8, color=RGBColor(0x33, 0x41, 0x55), align=PP_ALIGN.LEFT)

def slide1_colored_line(slide):
    """Boston (blue) vs. Raleigh (green) coloured subtitle."""
    left = Inches(0.5)
    top  = Inches(2.2)
    w    = W - Inches(1)
    h    = Inches(0.8)
    txBox = slide.shapes.add_textbox(left, top, w, h)
    tf = txBox.text_frame
    tf.word_wrap = False
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER

    def run(text, color, bold=True, size=36):
        r = p.add_run()
        r.text = text
        r.font.size  = Pt(size)
        r.font.bold  = bold
        r.font.color.rgb = color
        return r

    run("Boston", BLUE)
    run("  vs.  ", WHITE, bold=False, size=32)
    run("Raleigh", GREEN)
    return txBox

def slide2_overview(prs):
    s = blank_slide(prs)
    set_bg(s, BG)
    eyebrow(s, "At a Glance")
    heading(s, "Key Findings")
    divider(s, PURPLE)

    cw = Inches(3.6)
    ch = Inches(1.8)
    ct = Inches(2.4)
    gap = Inches(0.25)
    total_w = cw * 3 + gap * 2
    cl = (W - total_w) / 2

    add_card(s, cl,             ct, cw, ch, "BOSTON MEDIAN BASE PAY",  "$130,000", "per year",          BLUE)
    add_card(s, cl + cw + gap,  ct, cw, ch, "RALEIGH MEDIAN BASE PAY", "$104,000", "per year",          GREEN)
    add_card(s, cl + (cw+gap)*2, ct, cw, ch, "PAY PREMIUM",            "+25%",    "Boston over Raleigh", PURPLE)

    add_textbox(s,
        "Boston veterinarians command significantly higher salaries, reflecting the region's\n"
        "higher cost of living and denser demand for specialized veterinary services.",
        Inches(1.5), Inches(4.5), W - Inches(3), Inches(1),
        font_size=13, color=MUTED, align=PP_ALIGN.CENTER)

def slide3_boston(prs):
    s = blank_slide(prs)
    set_bg(s, RGBColor(0x10, 0x18, 0x28))
    eyebrow(s, "Market Deep-Dive")

    tb = s.shapes.add_textbox(Inches(0.5), Inches(1.0), W - Inches(1), Inches(0.8))
    tf = tb.text_frame
    p  = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r1 = p.add_run(); r1.text = "Boston, MA"; r1.font.size = Pt(34); r1.font.bold = True; r1.font.color.rgb = BLUE
    r2 = p.add_run(); r2.text = "  ·  Veterinarian Salaries"; r2.font.size = Pt(28); r2.font.bold = True; r2.font.color.rgb = WHITE

    divider(s, BLUE, Inches(2.0))

    cw = Inches(5.5); ch = Inches(1.7); gap = Inches(0.3)
    cl = (W - cw*2 - gap) / 2; ct = Inches(2.4)
    add_card(s, cl,        ct,        cw, ch, "MEDIAN BASE PAY",       "$130,000",    "annual, all experience levels", BLUE)
    add_card(s, cl+cw+gap, ct,        cw, ch, "SALARY RANGE",          "$85K – $185K","10th – 90th percentile",        BLUE)
    add_card(s, cl,        ct+ch+gap, cw, ch, "MOST COMMON PAY TYPE",  "Salary",      "annual",                        BLUE)
    add_card(s, cl+cw+gap, ct+ch+gap, cw, ch, "SALARY REPORTS",        "142",         "self-reported records",         BLUE)

    add_textbox(s, "Source: Glassdoor · Boston, MA metro area",
                Inches(0.5), H - Inches(0.6), W, Inches(0.3),
                font_size=8, color=RGBColor(0x33, 0x41, 0x55))

def slide4_raleigh(prs):
    s = blank_slide(prs)
    set_bg(s, RGBColor(0x0a, 0x14, 0x0e))
    eyebrow(s, "Market Deep-Dive")

    tb = s.shapes.add_textbox(Inches(0.5), Inches(1.0), W - Inches(1), Inches(0.8))
    tf = tb.text_frame
    p  = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r1 = p.add_run(); r1.text = "Raleigh, NC"; r1.font.size = Pt(34); r1.font.bold = True; r1.font.color.rgb = GREEN
    r2 = p.add_run(); r2.text = "  ·  Veterinarian Salaries"; r2.font.size = Pt(28); r2.font.bold = True; r2.font.color.rgb = WHITE

    divider(s, GREEN, Inches(2.0))

    cw = Inches(5.5); ch = Inches(1.7); gap = Inches(0.3)
    cl = (W - cw*2 - gap) / 2; ct = Inches(2.4)
    add_card(s, cl,        ct,        cw, ch, "MEDIAN BASE PAY",       "$104,000",    "annual, all experience levels", GREEN)
    add_card(s, cl+cw+gap, ct,        cw, ch, "SALARY RANGE",          "$72K – $148K","10th – 90th percentile",        GREEN)
    add_card(s, cl,        ct+ch+gap, cw, ch, "MOST COMMON PAY TYPE",  "Salary",      "annual",                        GREEN)
    add_card(s, cl+cw+gap, ct+ch+gap, cw, ch, "SALARY REPORTS",        "89",          "self-reported records",         GREEN)

    add_textbox(s, "Source: Glassdoor · Raleigh, NC metro area",
                Inches(0.5), H - Inches(0.6), W, Inches(0.3),
                font_size=8, color=RGBColor(0x33, 0x41, 0x55))

def slide5_bars(prs):
    s = blank_slide(prs)
    set_bg(s, RGBColor(0x16, 0x0d, 0x28))
    eyebrow(s, "Side-by-Side")
    heading(s, "Salary Range Comparison", top=Inches(0.9))
    divider(s, BLUE, Inches(1.9))

    rows = [
        ("Boston — Low",    "$85K",  0.46, BLUE),
        ("Boston — Median", "$130K", 0.70, BLUE),
        ("Boston — High",   "$185K", 1.00, BLUE),
        ("Raleigh — Low",   "$72K",  0.39, GREEN),
        ("Raleigh — Median","$104K", 0.56, GREEN),
        ("Raleigh — High",  "$148K", 0.80, GREEN),
    ]
    top = Inches(2.2)
    for i, (lbl, val, pct, col) in enumerate(rows):
        extra = Inches(0.2) if i == 3 else 0
        add_bar(s, lbl, val, pct, col, top + extra)
        top += Inches(0.75) + extra

    add_textbox(s, "Bars scaled to Boston high of $185K = 100%",
                Inches(0.5), H - Inches(0.6), W, Inches(0.3),
                font_size=8, color=RGBColor(0x33, 0x41, 0x55))

def slide6_table(prs):
    s = blank_slide(prs)
    set_bg(s, RGBColor(0x16, 0x0d, 0x28))
    eyebrow(s, "Detailed Breakdown")
    heading(s, "Boston vs. Raleigh — Head to Head", top=Inches(0.9))
    divider(s, PURPLE, Inches(1.9))

    col_xs = [Inches(0.4), Inches(4.1), Inches(7.0), Inches(9.9)]
    col_ws = [Inches(3.6), Inches(2.8), Inches(2.8), Inches(2.8)]
    row_h  = Inches(0.55)

    # header
    headers = ["Metric", "Boston, MA", "Raleigh, NC", "Difference"]
    hcolors = [MUTED, BLUE, GREEN, PURPLE]
    for text, x, w, c in zip(headers, col_xs, col_ws, hcolors):
        add_textbox(s, text.upper(),
                    x, Inches(2.15), w, Inches(0.35),
                    font_size=9, bold=True, color=c,
                    align=PP_ALIGN.CENTER if col_xs.index(x) > 0 else PP_ALIGN.LEFT)

    data = [
        ("Median Base Pay",          "$130,000", "$104,000", "+$26,000"),
        ("Low Estimate (10th %ile)", "$85,000",  "$72,000",  "+$13,000"),
        ("High Estimate (90th %ile)","$185,000", "$148,000", "+$37,000"),
        ("Salary Reports",           "142",      "89",       "—"),
        ("Cost-of-Living Index*",    "~162",     "~107",     "Boston +51%"),
    ]
    row_colors = [WHITE, BLUE, GREEN, PURPLE]

    for i, row in enumerate(data):
        top = Inches(2.55) + i * (row_h + Inches(0.08))
        add_table_row(s, row, top, col_xs, col_ws, row_h,
                      colors=[WHITE, BLUE, GREEN, PURPLE])

    add_textbox(s, "* Cost-of-living index: U.S. average = 100",
                Inches(0.4), H - Inches(0.6), W, Inches(0.3),
                font_size=8, color=RGBColor(0x33, 0x41, 0x55))

def slide7_method(prs):
    s = blank_slide(prs)
    set_bg(s, RGBColor(0x12, 0x0e, 0x04))
    eyebrow(s, "How We Got Here")
    heading(s, "Methodology", top=Inches(0.9))
    divider(s, AMBER, Inches(1.9))

    items = [
        ("🌐", "Data Source",  'Glassdoor salary pages for "Veterinarian" in Boston, MA and Raleigh, NC.'),
        ("🤖", "Scraper",      "Python using requests + optional Playwright + BeautifulSoup / JSON-LD extraction."),
        ("📊", "Parsing",      "Three-tier strategy — structured CSS class rows → JSON-LD schema.org objects → dollar-amount fallback."),
        ("💾", "Output",       "Records saved as timestamped CSV (output/vet_salaries_YYYYMMDD_HHMMSS.csv)."),
        ("⚠️", "Limitations",  "Self-reported salaries may have selection bias; Glassdoor may throttle automated requests."),
    ]
    top = Inches(2.2)
    for icon, label, desc in items:
        # icon box
        add_rect(s, Inches(0.5), top, Inches(0.55), Inches(0.45), CARD_BG)
        add_textbox(s, icon, Inches(0.5), top, Inches(0.55), Inches(0.45),
                    font_size=14, align=PP_ALIGN.CENTER)
        # bold label
        tb = s.shapes.add_textbox(Inches(1.2), top, W - Inches(1.5), Inches(0.45))
        tf = tb.text_frame
        p  = tf.paragraphs[0]
        r1 = p.add_run(); r1.text = label + ":  "; r1.font.size = Pt(12); r1.font.bold = True; r1.font.color.rgb = WHITE
        r2 = p.add_run(); r2.text = desc;           r2.font.size = Pt(12); r2.font.color.rgb = MUTED
        top += Inches(0.68)

# ── Main ───────────────────────────────────────────────────

def build():
    prs = new_prs()
    slide1_title(prs)
    slide2_overview(prs)
    slide3_boston(prs)
    slide4_raleigh(prs)
    slide5_bars(prs)
    slide6_table(prs)
    slide7_method(prs)
    prs.save("slide_deck.pptx")
    print("✓ slide_deck.pptx saved")

if __name__ == "__main__":
    build()
