# mdt-routes

Daily scrape of https://raider.io/weekly-routes for use by the
[mdt-visualizer](https://github.com/kw3r/mdt-visualizer) plugin.

The plugin fetches `raiderio_weekly.json` from the `main` branch
of this repo on every plugin load.

## Updating the dungeon list

When a new dungeon is added to `MAPPING_REGISTRY` in the plugin's
`main.lua`, add the corresponding entry to
`DUNGEON_NAME_TO_INSTANCE_ID` in `scripts/scrape.py`. The keys must
match the dungeon name as raider.io displays it on the weekly-routes
post.

## Manual run

```
python -m pip install -r scripts/requirements.txt
python scripts/scrape.py
```

Or trigger the workflow from the Actions tab via "Run workflow".

## Customizing the scraper

The HTML structure of raider.io's weekly-routes post is not stable
enough to enshrine. `scripts/scrape.py` has a `# CUSTOMIZE START ...
CUSTOMIZE END` block where the actual CSS selectors live; update them
when raider.io ships a redesign. The framework around the block
(fetch, validate, write JSON, exit non-zero on zero routes) is
deliberately structured so a broken selector fails loudly rather than
overwriting good data with empty.
