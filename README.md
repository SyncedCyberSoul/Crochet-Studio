# Crochet Studio 🧶

All in one home for crochet projects: what's on the hook, what's next, and photos of everything.

## Opening it

On the laptop, double-click **Start Crochet Studio.bat** in this folder.

- The first time, it spends a minute or two setting itself up.
- A black window opens and stays open. That window *is* the app, so leave it open while you use it and close it to stop.
- Your browser opens to **http://localhost:8000**. Bookmark it. Any browser on the laptop works; nothing else needs installing.

If it says Python isn't installed, get it from python.org, and during install tick **"Add python.exe to PATH"**.

> Opening it from the Mac, phone, or tablet comes in phase 5. For now it runs on the laptop only.

## What's in it

- **Profiles.** Pick who's crocheting. Passwords are optional: add one from the round initial at the top right, then **Profile & password**. Everyone's projects, patterns and ideas are their own.
- **Dashboard.** Projects are grouped by status: In progress, Planned, Idea, Paused, Done and Frogged. Search as you type, or tap a **#tag** to filter.
- **Projects and photos.** Add photos to any project (phone photos are turned the right way up). Moving a project to *In progress* or *Done* fills in the dates.
- **Patterns, step by step.** Under **Patterns**, paste a pattern's text and tap **Split into steps**: each row or round becomes a step (fix any odd splits before saving). Attach the PDF too. Link the pattern to a project, then tap **Follow pattern** for a big one-step-at-a-time view with row and stitch counters and a **US/UK terms** switch. Every tap saves on its own; if the connection drops it keeps the change on the device and retries, and it reopens where she left off. "Keep screen on" stops the phone sleeping mid-row.
- **Ideas.** Paste a Pinterest pin (or any link) and the picture and title fill themselves in, or snap a photo. **Make it a project** turns an idea into a planned project.
- **Discover.** Fresh projects from crochet blogs and r/crochet, with one-tap save to Ideas, plus a Pinterest search button. The admin can change the sources (Pinterest boards work: `https://www.pinterest.com/USER/BOARD.rss`).
- **3D.** Turn a photo of a finished piece into a model you can spin around (it works best when the piece stands out from the background), or open a GLB/STL/OBJ file. Drag to spin, pinch to zoom, and use the Puffiness slider.
- **Dark mode.** It follows the device's setting; tap the moon or sun at the top to switch.
- **What's new.** After an update, each profile gets one popup listing the new features. Add entries in `app/whatsnew.py`.

## Admin

The small **Admin logon** link at the bottom right isn't a profile, just a password. It lets you see every profile, open anyone's studio, add or rename profiles, reset or remove their passwords, and edit the Discover sources.

**First time:** open **http://localhost:8000/admin** on the laptop itself and choose the admin password. For safety, it can't be set from another device or through the internet.

> To look around without using up Jillian's one-time welcome note, use Admin → **Open** on her profile. No popups show while the admin is looking.

## Where your stuff lives

Everything is in the `data` folder next to this file:

- `data/crochet.db` holds all the project details.
- `data/media/` holds the photos, PDFs and 3D models.
- `data/secret.key` signs the login cookies. Back it up with the rest; if it's lost, everyone just picks their profile again.

**To back up by hand:** close the app, then copy the whole `data` folder somewhere safe, such as OneDrive or a USB stick. Automatic nightly backups come in phase 5.

The locations can be changed in `config.toml`.

## For whoever maintains it

- Requires Python 3.12+. The start file creates `.venv` and installs `requirements.txt` on first run. To do it by hand, run `python -m venv .venv`, then `.venv\Scripts\pip install -r requirements.txt`, then `.venv\Scripts\python run.py`.
- Keep the folder at a short path (e.g. `C:\CrochetStudio`): deeply nested folders break SQLAlchemy's DLLs on Windows.
- If `requirements.txt` changes later, delete `.venv` and run the start file again.
- Use `run.py --reload` to restart automatically while editing code.
- Stack: FastAPI, SQLModel (SQLite), Jinja2, HTMX, Alpine and three.js (in `app/static/vendor`, no build step), and Pillow. No other dependencies: logins use Python's own `hashlib`/`hmac`, and fetching from the internet uses `urllib`.
- Fetching links (Ideas, Discover) only goes to public internet addresses, never the laptop or home network (`app/webfetch.py`).
- Photo-to-3D (`app/photo3d.py`) needs no AI service. It finds the piece from colour clusters that stay away from the photo's edges, then inflates the outline into a rounded shape.
- New model fields are added to existing tables automatically on startup (`app/db.py`). Renaming or removing a column still needs a manual migration.
