# Reference frames

Drop a frame from the **original** Wind Waker here, named after the shot it matches:

    outset_harbour.png
    outset_beach.png
    outset_village.png
    outset_bridge.png
    outset_open_sea.png
    outset_sunset.png

Anything of the same view works - a Dolphin screenshot, a frame grabbed from a video, a
capture from real hardware. It does not have to be pixel-aligned; the report puts it beside
ours and measures the mean colour of three horizontal bands (sky / middle / foreground) so
the palette drift is a number rather than an opinion.

The shot list itself is `tools/ww_compare_shots.json` - camera eye, look-at point and hour,
so our side is reproducible run to run. Add a shot there and it appears in the report.
