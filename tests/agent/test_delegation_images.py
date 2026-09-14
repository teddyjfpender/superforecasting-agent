"""Image delegation routes pixels only to vision-capable children."""

import base64

from agent.delegation_images import goal_with_images


def test_native_images_include_local_remote_and_inline_without_base64_text(tmp_path):
    image = tmp_path / "chart.png"
    image.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aD1sAAAAASUVORK5CYII="
        )
    )
    inline = "data:image/png;base64,YQ=="
    parts = goal_with_images(
        "Read chart",
        [
            str(image),
            "https://example.org/chart.png",
            inline,
            str(tmp_path / "missing.png"),
        ],
        provider="test",
        model="vision",
        config={"agent": {"image_input_mode": "native"}},
    )
    pixels = [p["image_url"]["url"] for p in parts if p["type"] == "image_url"]
    assert len(pixels) == 3
    assert pixels[0].startswith("data:image/png;base64,")
    assert pixels[1:] == ["https://example.org/chart.png", inline]
    assert inline not in parts[0]["text"]
    assert "missing.png" not in parts[0]["text"]


def test_nonvision_gets_handles_and_explicit_inline_limitation():
    inline = "data:image/png;base64,YQ=="
    goal = goal_with_images(
        "Read chart",
        ["https://example.org/chart.png", inline],
        provider="test",
        model="text",
        config={"agent": {"image_input_mode": "text"}},
    )
    assert "vision_analyze" in goal and "https://example.org/chart.png" in goal
    assert "inline image(s) unavailable" in goal
    assert inline not in goal
