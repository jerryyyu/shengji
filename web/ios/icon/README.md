# App icon

`tractor-icon.svg` is the source of the iOS app icon: a gold vintage tractor, one solid glyph with the wheels cut out, on a bright green gradient.
`App/App/Assets.xcassets/AppIcon.appiconset/AppIcon-512@2x.png` is it rendered at 1024×1024 and flattened to
an opaque PNG (the App Store rejects an icon with an alpha channel):

```
# render the SVG at 1024x1024 in any browser or rasterizer, then drop alpha:
sips -s format jpeg -s formatOptions 100 icon.png --out icon.jpg && sips -s format png icon.jpg --out AppIcon-512@2x.png
```

iOS rounds the corners itself; the artwork is a full square.
