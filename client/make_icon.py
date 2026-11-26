import math
from PIL import Image, ImageDraw, ImageFilter, ImageFont

def make_icon():
    S = 1024  # Render at high res then downscale
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Background rounded hexagon/shield
    cx, cy = S // 2, S // 2
    r = 450

    # Draw rounded dark background badge
    # Outer glow rings
    for offset in range(30, 0, -5):
        alpha = int(25 * (1 - offset / 30))
        draw.rounded_rectangle(
            [cx - r - offset, cy - r - offset, cx + r + offset, cy + r + offset],
            radius=180,
            fill=(0, 240, 255, alpha),
            outline=(0, 255, 102, alpha),
            width=6
        )

    # Main dark body
    draw.rounded_rectangle(
        [cx - r, cy - r, cx + r, cy + r],
        radius=160,
        fill=(10, 15, 26, 255),
        outline=(0, 240, 255, 255),
        width=16
    )

    # Inner border neon green
    draw.rounded_rectangle(
        [cx - r + 24, cy - r + 24, cx + r - 24, cy + r - 24],
        radius=140,
        outline=(0, 255, 102, 200),
        width=8
    )

    # 2. Circuit traces / Tech grid lines in background
    trace_color = (0, 240, 255, 60)
    # Horizontal & vertical tech lines
    draw.line([cx - r + 80, cy - 200, cx - 200, cy - 200], fill=trace_color, width=6)
    draw.line([cx - 200, cy - 200, cx - 200, cy - 350], fill=trace_color, width=6)
    draw.ellipse([cx - 200 - 12, cy - 350 - 12, cx - 200 + 12, cy - 350 + 12], fill=(0, 255, 102, 180))

    draw.line([cx + r - 80, cy + 200, cx + 200, cy + 200], fill=trace_color, width=6)
    draw.line([cx + 200, cy + 200, cx + 200, cy + 350], fill=trace_color, width=6)
    draw.ellipse([cx + 200 - 12, cy + 350 - 12, cx + 200 + 12, cy + 350 + 12], fill=(0, 240, 255, 180))

    draw.line([cx - r + 80, cy + 200, cx - 200, cy + 200], fill=trace_color, width=6)
    draw.line([cx + r - 80, cy - 200, cx + 200, cy - 200], fill=trace_color, width=6)

    # 3. Medical Cross + Telemetry / Lightning in the center
    # Medical Cross dimensions
    cw = 120  # arm half width
    cl = 320  # arm length

    cross_color = (0, 255, 102, 240)
    cross_glow = (0, 255, 102, 80)
    
    # Glow for cross
    draw.rectangle([cx - cw - 20, cy - cl - 20, cx + cw + 20, cy + cl + 20], fill=cross_glow)
    draw.rectangle([cx - cl - 20, cy - cw - 20, cx + cl + 20, cy + cw + 20], fill=cross_glow)

    # Medical cross body
    draw.rectangle([cx - cw, cy - cl, cx + cw, cy + cl], fill=(13, 30, 24, 255), outline=(0, 255, 102, 255), width=10)
    draw.rectangle([cx - cl, cy - cw, cx + cl, cy + cw], fill=(13, 30, 24, 255), outline=(0, 255, 102, 255), width=10)

    # 4. Stylized Lightning bolt (⚡) cutting through the center
    # Bolt coordinates: zigzag
    bolt_points = [
        (cx + 60, cy - 260),
        (cx - 100, cy + 10),
        (cx + 10, cy + 10),
        (cx - 60, cy + 260),
        (cx + 110, cy - 10),
        (cx - 10, cy - 10),
    ]

    # Glow under lightning bolt
    draw.polygon(bolt_points, fill=(255, 230, 0, 255))
    draw.line(bolt_points + [bolt_points[0]], fill=(255, 255, 255, 255), width=8)

    # Pulse / Heartbeat ECG line through center
    ecg_color = (0, 240, 255, 240)
    ecg_points = [
        (cx - cl + 20, cy),
        (cx - 150, cy),
        (cx - 110, cy - 70),
        (cx - 70, cy + 80),
        (cx - 30, cy - 110),
        (cx + 30, cy + 110),
        (cx + 70, cy - 80),
        (cx + 110, cy + 70),
        (cx + 150, cy),
        (cx + cl - 20, cy)
    ]
    draw.line(ecg_points, fill=ecg_color, width=14, joint="curve")

    # 5. Text "IN4" at the bottom badge
    # Draw dark pill for text
    bw, bh = 240, 80
    by = cy + r - 120
    draw.rounded_rectangle([cx - bw, by - bh//2, cx + bw, by + bh//2], radius=30, fill=(5, 10, 18, 255), outline=(0, 240, 255, 255), width=6)
    
    # Try loading bold font, else draw clean vector IN4
    try:
        font = ImageFont.truetype("arialbd.ttf", 64)
        bbox = draw.textbbox((0, 0), "IN4.EXE", font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text((cx - tw//2, by - th//2 - 6), "IN4.EXE", font=font, fill=(0, 255, 102, 255))
    except Exception:
        pass

    # Save PNG and multi-resolution ICO
    out_dir = r"C:\Users\BVA\.gemini\antigravity\scratch\hospital_pc_inventory\client"
    png_path = f"{out_dir}\\app_icon.png"
    ico_path = f"{out_dir}\\app_icon.ico"
    
    img_256 = img.resize((256, 256), Image.Resampling.LANCZOS)
    img_256.save(png_path)

    # Multi-resolution ICO: 256, 128, 64, 48, 32, 16
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    icon_images = [img.resize(s, Image.Resampling.LANCZOS) for s in sizes]
    icon_images[0].save(ico_path, format="ICO", sizes=sizes)
    print("Icon generated successfully:", ico_path)

if __name__ == "__main__":
    make_icon()
