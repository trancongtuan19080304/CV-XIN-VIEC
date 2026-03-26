import base64
import html
import io
import os
import urllib.request
from datetime import datetime
from pathlib import Path

import streamlit as st
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


st.set_page_config(page_title="CV Xin Viec", page_icon="📄", layout="wide")

_APP_DIR = Path(__file__).resolve().parent

# Trên Streamlit Cloud (Linux) không có C:/Windows/Fonts — cần TTF hỗ trợ Unicode (tiếng Việt).
_LINUX_VIETNAMESE_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-VF.ttf",
    "/usr/share/fonts/opentype/noto/NotoSans-Regular.ttf",
]


_UNIVERSAL_FONT_ID = "VNFont_Universal"
# NotoSans có support Unicode tốt (tiếng Việt). Raw GitHub URL.
_UNIVERSAL_FONT_DOWNLOAD_URL = "https://raw.githubusercontent.com/googlefonts/noto-fonts/main/hinted/ttf/NotoSans/NotoSans-Regular.ttf"


def _collect_unicode_pdf_font_paths() -> list[Path]:
    """Ưu tiên font kèm repo, sau đó font có sẵn trên Linux (deploy).

    Trên Streamlit Cloud có thể không cài sẵn toàn bộ font ở /usr/share/fonts.
    Vì vậy nếu các đường dẫn định sẵn không tồn tại, mình sẽ quét thêm.
    """
    ordered: list[Path] = []

    # 1) Font đi kèm repo (nếu bạn copy font vào `fonts/`)
    bundled = _APP_DIR / "fonts"
    if bundled.is_dir():
        ordered.extend(sorted(bundled.glob("*.ttf")))
        ordered.extend(sorted(bundled.glob("*.TTF")))

    # 2) Các đường dẫn phổ biến (nếu tồn tại)
    for p in _LINUX_VIETNAMESE_FONT_CANDIDATES:
        pp = Path(p)
        if pp.is_file():
            ordered.append(pp)

    # 3) Nếu vẫn chưa có gì, scan các thư mục font phổ biến để tìm font Unicode
    if len(ordered) < 2:
        search_roots = [
            Path("/usr/share/fonts"),
            Path("/usr/local/share/fonts"),
            Path("/root/.local/share/fonts"),
            Path.home() / ".fonts",
        ]
        needles = [
            "noto", "dejavu", "liberation", "freefont", "ubuntu", "verdana", "arial", "tahoma", "sans",
        ]
        results: list[tuple[int, Path]] = []

        for root in search_roots:
            if not root.is_dir():
                continue
            try:
                for idx, ttf in enumerate(root.rglob("*.ttf")):
                    name = ttf.name.lower()
                    score = 0
                    for n in needles:
                        if n in name:
                            score += 10
                    # ưu tiên font sans/regular, giảm font icon/mono
                    if "bold" in name:
                        score += 1
                    if "regular" in name or "sans" in name:
                        score += 2
                    if "fontawesome" in name or "icon" in name:
                        score -= 50

                    if score > 0:
                        results.append((score, ttf))

                    # tránh quét quá lâu
                    if idx > 1200:
                        break
                    if len(results) >= 80:
                        break
            except Exception:
                continue

        results.sort(key=lambda x: (-x[0], str(x[1])))
        for _, ttf in results[:40]:
            if ttf not in ordered:
                ordered.append(ttf)

    return ordered


def _register_ttf_once(font_id: str, font_path: str | Path) -> bool:
    path_str = str(font_path) if font_path else ""
    if not path_str or not Path(path_str).is_file():
        return False
    try:
        if font_id in pdfmetrics.getRegisteredFontNames():
            return True
        pdfmetrics.registerFont(TTFont(font_id, path_str))
        return True
    except Exception:
        return False


FONT_CONFIGS = {
    "Arial": {
        "css": "'Arial', sans-serif",
        "paths": ["C:/Windows/Fonts/arial.ttf"],
    },
    "Calibri": {
        "css": "'Calibri', 'Arial', sans-serif",
        "paths": ["C:/Windows/Fonts/calibri.ttf"],
    },
    "Tahoma": {
        "css": "'Tahoma', 'Arial', sans-serif",
        "paths": ["C:/Windows/Fonts/tahoma.ttf"],
    },
    "Times New Roman": {
        "css": "'Times New Roman', serif",
        "paths": ["C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/timesbd.ttf"],
    },
    "Verdana": {
        "css": "'Verdana', 'Arial', sans-serif",
        "paths": ["C:/Windows/Fonts/verdana.ttf"],
    },
    "Georgia": {
        "css": "'Georgia', serif",
        "paths": ["C:/Windows/Fonts/georgia.ttf"],
    },
    "Courier New": {
        "css": "'Courier New', monospace",
        "paths": ["C:/Windows/Fonts/cour.ttf"],
    },
    "Trebuchet MS": {
        "css": "'Trebuchet MS', 'Arial', sans-serif",
        "paths": ["C:/Windows/Fonts/trebuc.ttf"],
    },
}


TEMPLATE_PRESETS = {
    # Phong cách giữ nguyên với mẫu hiện tại của bạn
    "Vintage Kem (Mặc định)": {
        "accent": "#8a7364",
        "text": "#3a3a3a",
        "soft_text": "#3c3c3c",
        "year_bg": "#3a3a3a",
        "year_text": "#ffffff",
    },
    "Modern Xanh": {
        "accent": "#2a6f97",
        "text": "#1f2a37",
        "soft_text": "#2b3547",
        "year_bg": "#0f4d6a",
        "year_text": "#ffffff",
    },
    "Minimal Đen Trắng": {
        "accent": "#111111",
        "text": "#1a1a1a",
        "soft_text": "#2a2a2a",
        "year_bg": "#1a1a1a",
        "year_text": "#ffffff",
    },
    "Pastel Hồng": {
        "accent": "#b86b6b",
        "text": "#3a2a2a",
        "soft_text": "#3f2f2f",
        "year_bg": "#7a4d4d",
        "year_text": "#ffffff",
    },
}


def _get_template_style(template_name: str) -> dict:
    return TEMPLATE_PRESETS.get(template_name, TEMPLATE_PRESETS["Vintage Kem (Mặc định)"])


def _register_font_if_possible(selected_font: str) -> str:
    configs = FONT_CONFIGS.get(selected_font, FONT_CONFIGS["Arial"])
    preferred_id = f"VNFont_{selected_font.replace(' ', '_')}"
    for font_path in configs["paths"]:
        if _register_ttf_once(preferred_id, font_path):
            return preferred_id

    # Universal font: luôn cố gắng có Unicode để tránh lỗi ô vuông.
    universal_id = _UNIVERSAL_FONT_ID

    # 1) Ưu tiên font có trong repo `fonts/`
    bundled_dir = _APP_DIR / "fonts"
    bundled_candidates = [
        bundled_dir / "NotoSans-Regular.ttf",
        bundled_dir / "NotoSans-VF.ttf",
        bundled_dir / "DejaVuSans.ttf",
        bundled_dir / "LiberationSans-Regular.ttf",
    ]
    for p in bundled_candidates:
        if _register_ttf_once(universal_id, p):
            return universal_id

    # 2) Nếu repo không có font, thử tải về (Streamlit Cloud thường có internet).
    try:
        if not bundled_dir.exists():
            bundled_dir.mkdir(parents=True, exist_ok=True)
        target = bundled_dir / "NotoSans-Regular.ttf"
        if not target.is_file():
            urllib.request.urlretrieve(_UNIVERSAL_FONT_DOWNLOAD_URL, str(target))
        if _register_ttf_once(universal_id, target):
            return universal_id
    except Exception:
        pass

    # 3) Cuối cùng: dùng các font phổ biến có sẵn trên Linux (nếu có)
    for candidate in _collect_unicode_pdf_font_paths():
        if _register_ttf_once(universal_id, candidate):
            return universal_id

    for font_path in [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/tahoma.ttf",
        "C:/Windows/Fonts/times.ttf",
    ]:
        if _register_ttf_once(universal_id, font_path):
            return universal_id
    st.error(
        "Không thể đăng ký font Unicode cho PDF. Vui lòng thêm file font TTF vào thư mục `fonts/` "
        "(ví dụ `fonts/NotoSans-Regular.ttf`) và redeploy Streamlit."
    )
    return "Helvetica"


def _safe_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _parse_education(raw: str) -> list[dict]:
    rows = []
    for line in _safe_lines(raw):
        parts = [item.strip() for item in line.split("|")]
        if len(parts) >= 3:
            rows.append({"school": parts[0], "time": parts[1], "major": parts[2]})
        else:
            rows.append({"school": line, "time": "", "major": ""})
    return rows


def _parse_experience(raw: str) -> list[dict]:
    blocks = [b.strip() for b in raw.split("\n\n") if b.strip()]
    data = []
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        head = [h.strip() for h in lines[0].split("|")]
        if len(head) >= 3:
            year, company, role = head[0], head[1], head[2]
        else:
            year, company, role = "", lines[0], ""
        bullets = []
        for bullet in lines[1:]:
            cleaned = bullet.lstrip("-• ").strip()
            if cleaned:
                bullets.append(cleaned)
        data.append({"year": year, "company": company, "role": role, "bullets": bullets})
    return data


def _as_html_list(items: list[str]) -> str:
    return "".join(f"<li>{html.escape(item)}</li>" for item in items)


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    clean = hex_color.strip().lstrip("#")
    if len(clean) != 6:
        return (0.96, 0.94, 0.92)
    r = int(clean[0:2], 16) / 255
    g = int(clean[2:4], 16) / 255
    b = int(clean[4:6], 16) / 255
    return (r, g, b)


def _draw_gradient_background(
    pdf: canvas.Canvas,
    x: float,
    y: float,
    w: float,
    h: float,
    color_start: str,
    color_end: str,
    direction: str,
):
    steps = 140
    sr, sg, sb = _hex_to_rgb(color_start)
    er, eg, eb = _hex_to_rgb(color_end)
    for idx in range(steps):
        t = idx / max(steps - 1, 1)
        rr = sr + (er - sr) * t
        gg = sg + (eg - sg) * t
        bb = sb + (eb - sb) * t
        pdf.setFillColor(colors.Color(rr, gg, bb))
        if direction == "horizontal":
            strip_w = w / steps
            pdf.rect(x + idx * strip_w, y, strip_w + 0.6, h, stroke=0, fill=1)
        else:
            strip_h = h / steps
            pdf.rect(x, y + idx * strip_h, w, strip_h + 0.6, stroke=0, fill=1)


def _build_preview_html(data: dict, avatar_bytes: bytes | None) -> str:
    avatar_src = ""
    if avatar_bytes:
        avatar_src = base64.b64encode(avatar_bytes).decode("utf-8")
    avatar_html = (
        f'<img src="data:image/png;base64,{avatar_src}" class="avatar" />'
        if avatar_src
        else '<div class="avatar placeholder">Ảnh</div>'
    )

    education_html = ""
    for edu in data["education_list"]:
        education_html += (
            "<div class='edu-item'>"
            f"<div class='dot'>•</div>"
            f"<div><div class='strong'>{html.escape(edu['school'])}</div>"
            f"<div>{html.escape(edu['time'])} | {html.escape(edu['major'])}</div></div>"
            "</div>"
        )

    exp_html = ""
    for exp in data["experience_list"]:
        bullets_html = _as_html_list(exp["bullets"])
        exp_html += (
            "<div class='exp-item'>"
            f"<span class='year'>{html.escape(exp['year'])}</span>"
            "<div class='exp-body'>"
            f"<div class='strong'>{html.escape(exp['company'])}</div>"
            f"<div class='strong'>{html.escape(exp['role'])}</div>"
            f"<ul>{bullets_html}</ul>"
            "</div></div>"
        )

    skills_html = _as_html_list(data["skills_list"])
    bg_mode = data.get("bg_mode", "solid")
    if bg_mode == "gradient_horizontal":
        bg_css = f"linear-gradient(90deg, {data['bg_color_1']} 0%, {data['bg_color_2']} 100%)"
    elif bg_mode == "gradient_vertical":
        bg_css = f"linear-gradient(180deg, {data['bg_color_1']} 0%, {data['bg_color_2']} 100%)"
    else:
        bg_css = data.get("bg_color_1", "#f4f0eb")
    selected_font = data.get("font_choice", "Arial")
    css_font_family = FONT_CONFIGS.get(selected_font, FONT_CONFIGS["Arial"])["css"]
    template_name = data.get("template_name", "Vintage Kem (Mặc định)")
    template_style = _get_template_style(template_name)
    accent_color = template_style["accent"]
    text_color = template_style["text"]
    soft_text = template_style["soft_text"]
    year_bg = template_style["year_bg"]
    year_text = template_style["year_text"]
    return f"""
    <style>
      .cv-wrap {{
        background:{bg_css}; padding:22px; border-radius:6px;
        font-family: {css_font_family}; color:{text_color};
      }}
      .top {{ display:grid; grid-template-columns: 190px 1fr; gap:18px; align-items:start; }}
      .avatar {{
        width:176px; height:176px; object-fit:cover; border:2px solid #c9beb1;
        border-radius:50%; overflow:hidden; display:block;
      }}
      .placeholder {{
        display:flex; align-items:center; justify-content:center; background:#e6dfd6;
        color:#7b6c5e; font-weight:700;
      }}
      .name-main {{ font-size:68px; line-height:0.9; font-weight:900; color:{accent_color}; letter-spacing:1px; }}
      .name-sub {{ font-size:72px; line-height:0.8; color:{text_color}; margin-top:6px; }}
      .job {{ font-size:30px; font-weight:700; letter-spacing:1px; margin-top:10px; }}
      .intro {{
        margin:14px 0 10px;
        font-size:28px; line-height:1.28;
      }}
      .intro-title {{
        font-size:26px; color:{accent_color}; font-weight:900;
        letter-spacing:0.5px; margin:0 0 6px;
      }}
      .intro-body {{ font-size:24px; line-height:1.3; color:{soft_text}; }}
      .objective {{ margin:10px 0 0; }}
      .objective-title {{
        font-size:26px; color:{accent_color}; font-weight:900;
        letter-spacing:0.5px; margin:0 0 6px;
      }}
      .objective-body {{ font-size:24px; line-height:1.3; color:{soft_text}; }}
      .contact {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:12px; margin-bottom:16px; }}
      .label {{ font-size:30px; font-style:italic; font-weight:700; }}
      .value {{ font-size:27px; }}
      .bottom {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
      .section-title {{ font-size:44px; color:{accent_color}; font-weight:900; margin:10px 0 8px; }}
      .edu-item, .exp-item {{ display:flex; margin-bottom:10px; font-size:28px; line-height:1.35; }}
      .dot {{ width:22px; font-weight:bold; }}
      .strong {{ font-weight:700; }}
      .year {{
        background:{year_bg}; color:{year_text}; border-radius:6px; font-size:24px;
        font-weight:700; padding:2px 8px; height:max-content; margin-right:10px;
      }}
      .exp-body ul, .skills ul {{ margin:4px 0 0 18px; padding:0; }}
      .exp-body li, .skills li {{ margin-bottom:2px; font-size:27px; line-height:1.35; }}
    </style>
    <div class="cv-wrap">
      <div class="top">
        {avatar_html}
        <div>
          <div class="name-main">{html.escape(data["first_name"].upper())}</div>
          <div class="name-sub">{html.escape(data["signature_name"])}</div>
          <div class="job">{html.escape(data["job_title"].upper())}</div>
        </div>
      </div>
      <div class="objective">
        <div class="objective-title">MỤC TIÊU NGHỀ NGHIỆP</div>
        <div class="objective-body">{html.escape(data["career_objective"])}</div>
      </div>
      <div class="intro">
        <div class="intro-title">ĐOẠN GIỚI THIỆU NGẮN</div>
        <div class="intro-body">{html.escape(data["summary"])}</div>
      </div>
      <div class="contact">
        <div><div class="label">Email</div><div class="value">{html.escape(data["email"])}</div></div>
        <div><div class="label">Điện thoại</div><div class="value">{html.escape(data["phone"])}</div></div>
        <div><div class="label">Địa chỉ</div><div class="value">{html.escape(data["address"])}</div></div>
      </div>
      <div class="bottom">
        <div>
          <div class="section-title">HỌC VẤN</div>
          {education_html}
          <div class="section-title">KỸ NĂNG</div>
          <div class="skills"><ul>{skills_html}</ul></div>
        </div>
        <div>
          <div class="section-title">KINH NGHIỆM</div>
          {exp_html}
        </div>
      </div>
    </div>
    """


def _draw_wrapped_text(pdf: canvas.Canvas, text: str, x: float, y: float, max_width: float, line_h: float):
    words = text.split()
    line = ""
    for word in words:
        test = f"{line} {word}".strip()
        if pdf.stringWidth(test) <= max_width:
            line = test
        else:
            pdf.drawString(x, y, line)
            y -= line_h
            line = word
    if line:
        pdf.drawString(x, y, line)
        y -= line_h
    return y


def _build_pdf(data: dict, avatar_bytes: bytes | None) -> bytes:
    out = io.BytesIO()
    pdf = canvas.Canvas(out, pagesize=A4)
    width, height = A4
    font_name = _register_font_if_possible(data.get("font_choice", "Arial"))
    template_style = _get_template_style(data.get("template_name", "Vintage Kem (Mặc định)"))
    accent_color = template_style["accent"]
    text_color = template_style["text"]
    soft_text_color = template_style["soft_text"]
    year_bg = template_style["year_bg"]

    pad = 24
    bg_mode = data.get("bg_mode", "solid")
    bg_color_1 = data.get("bg_color_1", "#f4f0eb")
    bg_color_2 = data.get("bg_color_2", "#ffffff")
    if bg_mode == "solid":
        pdf.setFillColor(colors.HexColor(bg_color_1))
        pdf.rect(pad, pad, width - 2 * pad, height - 2 * pad, stroke=0, fill=1)
    elif bg_mode == "gradient_horizontal":
        _draw_gradient_background(
            pdf,
            pad,
            pad,
            width - 2 * pad,
            height - 2 * pad,
            bg_color_1,
            bg_color_2,
            "horizontal",
        )
    else:
        _draw_gradient_background(
            pdf,
            pad,
            pad,
            width - 2 * pad,
            height - 2 * pad,
            bg_color_1,
            bg_color_2,
            "vertical",
        )

    content_left = pad + 18
    content_top = height - pad - 18
    photo_w = 120
    photo_h = 120

    if avatar_bytes:
        try:
            img = ImageReader(io.BytesIO(avatar_bytes))
            path = pdf.beginPath()
            center_x = content_left + photo_w / 2
            center_y = content_top - photo_h / 2
            radius = photo_w / 2
            path.circle(center_x, center_y, radius)
            pdf.saveState()
            pdf.clipPath(path, stroke=0, fill=0)
            pdf.drawImage(img, content_left, content_top - photo_h, photo_w, photo_h, preserveAspectRatio=True, mask="auto")
            pdf.restoreState()
            pdf.setStrokeColor(colors.HexColor("#b4a79a"))
            pdf.setLineWidth(1.4)
            pdf.circle(center_x, center_y, radius, stroke=1, fill=0)
        except Exception:
            pdf.setStrokeColor(colors.HexColor("#b4a79a"))
            pdf.circle(content_left + photo_w / 2, content_top - photo_h / 2, photo_w / 2, stroke=1, fill=0)
    else:
        pdf.setStrokeColor(colors.HexColor("#b4a79a"))
        pdf.circle(content_left + photo_w / 2, content_top - photo_h / 2, photo_w / 2, stroke=1, fill=0)

    tx = content_left + photo_w + 12
    pdf.setFillColor(colors.HexColor(accent_color))
    pdf.setFont(font_name, 34)
    pdf.drawString(tx, content_top - 25, data["first_name"].upper())
    pdf.setFillColor(colors.HexColor(text_color))
    pdf.setFont(font_name, 30)
    pdf.drawString(tx, content_top - 58, data["signature_name"])
    pdf.setFont(font_name, 12)
    pdf.drawString(tx, content_top - 80, data["job_title"].upper())

    y = content_top - photo_h - 20

    # Mục tiêu nghề nghiệp
    pdf.setFillColor(colors.HexColor(accent_color))
    pdf.setFont(font_name, 12)
    pdf.drawString(content_left, y, "MỤC TIÊU NGHỀ NGHIỆP")
    y -= 14
    pdf.setFillColor(colors.HexColor(soft_text_color))
    pdf.setFont(font_name, 10.5)
    y = _draw_wrapped_text(pdf, data.get("career_objective", ""), content_left, y, width - content_left - 28, 13)

    # Đoạn giới thiệu ngắn
    y -= 8
    pdf.setFillColor(colors.HexColor(accent_color))
    pdf.setFont(font_name, 12)
    pdf.drawString(content_left, y, "ĐOẠN GIỚI THIỆU NGẮN")
    y -= 14
    pdf.setFillColor(colors.HexColor(soft_text_color))
    pdf.setFont(font_name, 10.5)
    y = _draw_wrapped_text(pdf, data["summary"], content_left, y, width - content_left - 28, 14)

    y -= 6
    col_w = (width - content_left - 32) / 3
    labels = [("Email", data["email"]), ("Điện thoại", data["phone"]), ("Địa chỉ", data["address"])]
    for idx, (label, val) in enumerate(labels):
        x = content_left + idx * col_w
        pdf.setFont(font_name, 11)
        pdf.drawString(x, y, label)
        pdf.setFont(font_name, 10)
        pdf.drawString(x, y - 14, val)

    left_x = content_left
    right_x = content_left + (width - content_left - 28) * 0.49
    section_y = y - 40

    pdf.setFillColor(colors.HexColor(accent_color))
    pdf.setFont(font_name, 15)
    pdf.drawString(left_x, section_y, "HỌC VẤN")
    cursor = section_y - 18
    pdf.setFillColor(colors.HexColor(text_color))
    for edu in data["education_list"]:
        text = f"• {edu['school']}"
        pdf.setFont(font_name, 10.5)
        pdf.drawString(left_x, cursor, text)
        cursor -= 13
        detail = f"{edu['time']} | {edu['major']}".strip(" |")
        pdf.setFont(font_name, 10)
        cursor = _draw_wrapped_text(pdf, detail, left_x + 10, cursor, (right_x - left_x) - 20, 12)
        cursor -= 4

    pdf.setFillColor(colors.HexColor(accent_color))
    pdf.setFont(font_name, 15)
    pdf.drawString(left_x, cursor - 4, "KỸ NĂNG")
    cursor -= 22
    pdf.setFillColor(colors.HexColor(text_color))
    pdf.setFont(font_name, 10.5)
    for skill in data["skills_list"]:
        pdf.drawString(left_x, cursor, f"• {skill}")
        cursor -= 13

    pdf.setFillColor(colors.HexColor(accent_color))
    pdf.setFont(font_name, 15)
    pdf.drawString(right_x, section_y, "KINH NGHIỆM")
    rc = section_y - 18
    for exp in data["experience_list"]:
        pdf.setFillColor(colors.HexColor(year_bg))
        pdf.roundRect(right_x, rc - 2, 26, 13, 3, stroke=0, fill=1)
        pdf.setFillColor(colors.white)
        pdf.setFont(font_name, 9)
        pdf.drawString(right_x + 4, rc + 1, exp["year"][:4] if exp["year"] else "")
        pdf.setFillColor(colors.HexColor(text_color))
        pdf.setFont(font_name, 10.5)
        pdf.drawString(right_x + 32, rc, exp["company"])
        rc -= 12
        pdf.setFont(font_name, 10.5)
        pdf.drawString(right_x + 32, rc, exp["role"])
        rc -= 12
        pdf.setFont(font_name, 10)
        for bullet in exp["bullets"]:
            rc = _draw_wrapped_text(pdf, f"• {bullet}", right_x + 34, rc, width - right_x - 36, 12)
        rc -= 8

    pdf.save()
    out.seek(0)
    return out.getvalue()


st.markdown(
    """
    <style>
      .hero {
        padding: 18px 20px;
        border: 1px solid #e6e6e6;
        border-radius: 14px;
        background: linear-gradient(135deg, #f9f6f2 0%, #f2eee8 100%);
        margin-bottom: 14px;
      }
      .hero h2 {
        margin: 0;
        color: #5b4b40;
        font-size: 1.5rem;
      }
      .hero p {
        margin: 6px 0 0;
        color: #6c5d52;
        font-size: 0.95rem;
      }
      .small-note {
        color: #6e6e6e;
        font-size: 0.88rem;
      }
    </style>
    <div class="hero">
      <h2>📄 CV Builder</h2>
      <p>Điền thông tin bên trái, xem trước trực tiếp bên phải và tải PDF ngay.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

default_data = {
    "first_name": "NGUYỄN",
    "signature_name": "Yến Nhi",
    "job_title": "Chuyên viên thiết kế đồ họa",
    "email": "hello@reallygreatsite.com",
    "phone": "123-456-7890",
    "address": "123 Anywhere St., Any City",
    "template_name": "Vintage Kem (Mặc định)",
    "career_objective": "Mục tiêu của tôi là trở thành một thiết kế đồ họa chuyên nghiệp, nâng cao kỹ năng và đóng góp hiệu quả vào các dự án truyền thông.",
    "summary": "Tôi là một nhà Thiết kế Đồ họa chuyên nghiệp trong ngành, có khả năng kết hợp hình ảnh, chữ in nghệ thuật và vận động trong cùng một thiết kế.",
    "education_raw": (
        "ĐH Mỹ thuật Công nghiệp | 2024 - 2028 | Nghệ thuật đa phương tiện\n"
        "ĐH Mỹ thuật Công nghiệp | 2028 - 2029 | Khóa học Vẽ minh họa"
    ),
    "skills_raw": "Thiết kế đồ họa\nVẽ minh họa\nChụp ảnh\nĐồ họa chuyển động\nQuay phim\nTạo bố cục",
    "experience_raw": (
        "2028 | Công ty Thiết kế ABC | Thực tập Thiết kế đồ họa\n"
        "- Được giao nhiệm vụ thiết kế đồ họa cho các ấn phẩm ngoài tuyến.\n"
        "- Chỉnh sửa ảnh cho khách hàng, tạp chí và các bài đăng mạng xã hội.\n\n"
        "2029 | Công ty Thiết kế ABC | Nhân viên Thiết kế đồ họa\n"
        "- Hợp tác sâu với nhóm tiếp thị để tạo ý tưởng truyền thông.\n"
        "- Tạo ý tưởng chủ đề cho nhiều công ty khác."
    ),
}

left_col, right_col = st.columns([1, 1.2], gap="large")

with left_col:
    st.subheader("Thông tin CV")
    with st.container(border=True):
        st.markdown("**Thông tin cá nhân**")
        avatar_file = st.file_uploader("Ảnh đại diện", type=["png", "jpg", "jpeg"])
        name_col_1, name_col_2 = st.columns(2)
        with name_col_1:
            first_name = st.text_input("Họ lớn (dòng trên)", value=default_data["first_name"])
        with name_col_2:
            signature_name = st.text_input("Tên kiểu chữ ký (dòng dưới)", value=default_data["signature_name"])
        job_title = st.text_input("Vị trí công việc", value=default_data["job_title"])
        summary = st.text_area("Đoạn giới thiệu ngắn", value=default_data["summary"], height=110)
        career_objective = st.text_area(
            "Mục tiêu nghề nghiệp",
            value=default_data["career_objective"],
            height=90,
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            email = st.text_input("Email", value=default_data["email"])
        with c2:
            phone = st.text_input("Điện thoại", value=default_data["phone"])
        with c3:
            address = st.text_input("Địa chỉ", value=default_data["address"])

    with st.container(border=True):
        st.markdown("**Học vấn**")
        st.caption("Định dạng: `Trường | Thời gian | Chuyên ngành` (mỗi dòng 1 mục)")
        education_raw = st.text_area(
            "education_raw",
            value=default_data["education_raw"],
            height=110,
            label_visibility="collapsed",
        )

    with st.container(border=True):
        st.markdown("**Kỹ năng**")
        st.caption("Mỗi dòng là một kỹ năng")
        skills_raw = st.text_area(
            "skills_raw",
            value=default_data["skills_raw"],
            height=120,
            label_visibility="collapsed",
        )

    with st.container(border=True):
        st.markdown("**Kinh nghiệm**")
        with st.expander("Xem mẫu nhập dữ liệu", expanded=False):
            st.code(
                "2028 | Công ty A | Vị trí\n"
                "- Gạch đầu dòng 1\n"
                "- Gạch đầu dòng 2\n\n"
                "2029 | Công ty B | Vị trí\n"
                "- Nội dung 1",
                language="text",
            )
        experience_raw = st.text_area(
            "experience_raw",
            value=default_data["experience_raw"],
            height=220,
            label_visibility="collapsed",
        )

    with st.container(border=True):
        st.markdown("**Mẫu CV**")
        st.caption("Thay đổi màu nhấn cho tiêu đề, năm kinh nghiệm và chữ chính.")
        template_name = st.selectbox(
            "Chọn phong cách",
            list(TEMPLATE_PRESETS.keys()),
            index=0,
        )

    with st.container(border=True):
        st.markdown("**Tùy chỉnh nền CV**")
        preset_options = {
            "Mặc định (kem nhạt)": ("solid", "#f4f0eb", "#f4f0eb"),
            "Hồng pastel": ("solid", "#f7ebef", "#f7ebef"),
            "Xanh mint": ("solid", "#e8f5f0", "#e8f5f0"),
            "Cam nhạt -> Trắng (dọc)": ("gradient_vertical", "#f6e6d4", "#fffdf8"),
            "Xanh -> Tím pastel (ngang)": ("gradient_horizontal", "#e7f0ff", "#efe9ff"),
            "Tùy chỉnh thủ công": ("solid", "#f4f0eb", "#ffffff"),
        }
        selected_preset = st.selectbox("Bảng màu", list(preset_options.keys()))

        if selected_preset == "Tùy chỉnh thủ công":
            selected_mode_label = st.radio(
                "Kiểu nền",
                ["Màu đơn", "Phối dọc", "Phối ngang"],
                horizontal=True,
            )
            if selected_mode_label == "Màu đơn":
                bg_mode = "solid"
            elif selected_mode_label == "Phối ngang":
                bg_mode = "gradient_horizontal"
            else:
                bg_mode = "gradient_vertical"
            bg_color_1 = st.color_picker("Màu 1", value="#f4f0eb")
            bg_color_2 = st.color_picker("Màu 2", value="#ffffff") if bg_mode != "solid" else bg_color_1
        else:
            bg_mode, bg_color_1, bg_color_2 = preset_options[selected_preset]
            st.caption(f"Đang dùng preset: `{selected_preset}`")

    with st.container(border=True):
        st.markdown("**Tùy chỉnh font chữ**")
        font_choice = st.selectbox(
            "Font hiển thị",
            list(FONT_CONFIGS.keys()),
            index=0,
            help="Font sẽ áp dụng cho cả bản xem trước và file PDF.",
        )
        st.caption(f"Font đang dùng: `{font_choice}`")

cv_data = {
    "first_name": first_name,
    "signature_name": signature_name,
    "job_title": job_title,
    "career_objective": career_objective,
    "summary": summary,
    "email": email,
    "phone": phone,
    "address": address,
    "template_name": template_name,
    "education_list": _parse_education(education_raw),
    "skills_list": _safe_lines(skills_raw),
    "experience_list": _parse_experience(experience_raw),
    "bg_mode": bg_mode,
    "bg_color_1": bg_color_1,
    "bg_color_2": bg_color_2,
    "font_choice": font_choice,
}

avatar_bytes = avatar_file.getvalue() if avatar_file else None
preview_html = _build_preview_html(cv_data, avatar_bytes)
pdf_bytes = _build_pdf(cv_data, avatar_bytes)

with right_col:
    st.subheader("Xem trước theo mẫu")
    st.markdown('<p class="small-note">Bản xem trước cập nhật theo dữ liệu bạn nhập.</p>', unsafe_allow_html=True)
    st.markdown(preview_html, unsafe_allow_html=True)
    st.download_button(
        label="⬇️ Tải CV PDF",
        data=pdf_bytes,
        file_name=f"CV_{signature_name.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf",
        mime="application/pdf",
        type="primary",
        use_container_width=True,
    )
