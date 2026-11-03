# Crochet Studio 🧶

Jillian's home for crochet projects: what's on the hook, what's next, and photos of everything.

## Opening it

On the laptop, in this folder:

```
python run.py
```

Then open **http://localhost:8000** in a browser. Leave that window open while you use it; close it to stop the app.

> Opening it from the Mac, phone, or tablet comes in phase 5. For now it runs on the laptop only.

## What's in it so far (phase 1)

- **Dashboard.** Projects are grouped by status: In progress, Planned, Idea, Paused, Done and Frogged. Tap a group's heading to fold it away.
- **Search.** Type in the search box and results narrow as you type. It looks at names, who a project is for, notes, hook size and tags. Tap a **#tag** chip to show only that tag, and tap it again to clear.
- **Projects.** Tap **+ New project** to add one. On a project's page, tap a status button to move it along. Moving to *In progress* fills in the start date, and *Done* fills in the finish date, unless you've already set them.
- **Photos.** Add as many as you like. Phone photos are turned the right way up and shrunk to a sensible size. Tap a photo to see it big, tap its caption to edit it, or use **Make cover** to choose the project's main picture.

## Where your stuff lives

Everything is in the `data` folder next to this file:

- `data/crochet.db` holds all the project details.
- `data/media/` holds the photos.

**To back up by hand:** close the app, then copy the whole `data` folder somewhere safe, such as OneDrive or a USB stick. Automatic nightly backups come in phase 5.

The locations can be changed in `config.toml`.

## For whoever maintains it

- Requires Python 3.12+. Install with `python -m venv .venv`, then `.venv\Scripts\pip install -r requirements.txt`.
- Use `python run.py --reload` to restart automatically while editing code.
- Stack: FastAPI, SQLModel (SQLite), Jinja2, HTMX and Alpine (in `app/static/vendor`, no build step), and Pillow.
- New model fields are added to existing tables automatically on startup (`app/db.py`). Renaming or removing a column still needs a manual migration.
