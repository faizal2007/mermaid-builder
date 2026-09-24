# Diagram Maker — Privacy Policy

**Applies to:** Diagram Maker for Windows (version 0.2.1 and later)
**Publisher:** Faizal Sadri
**Effective date:** 24 September 2026

## In short

Diagram Maker is an offline desktop application. It has no user accounts, no
advertising, no analytics, and no telemetry. Your diagrams stay on your computer.
The only network request the app makes is a download of the mermaid.js rendering
library, needed to draw the live preview.

## Information we collect

**None.** We do not collect, transmit, store, sell or share any personal
information. Specifically, the application does not collect:

- names, email addresses, or any other contact details;
- account credentials or sign-in data;
- diagrams, diagram content, file names or file paths;
- usage, diagnostic, crash or performance data;
- advertising identifiers, device identifiers or location data.

We have no servers that receive data from the application, and we cannot see what
you build with it.

## Where your work is stored

Everything you create stays under your control, on your own device:

- **Diagrams.** Saved to the `.json` files you choose, and exported to `.mmd`,
  `.html` or `.svg` files you choose. They are never uploaded anywhere.
- **Settings and preferences.** Held in memory for the session only. The app
  writes no configuration to the registry or to a user profile folder, and it
  gives the preview engine no persistent browser profile, so anything that
  engine caches is kept in memory for the session.
- **Temporary preview file.** If the embedded preview engine is unavailable, the
  app writes the current diagram to a single file named
  `diagram-maker-preview.html` in your system temporary folder so it can be
  opened in your web browser. It contains only that diagram, is overwritten on
  each use, and is removed by the normal cleanup of temporary files.

## Network access

The preview pane needs the mermaid.js library to render diagrams. It downloads
that one file, and nothing else, from the jsDelivr content delivery network when
the preview loads (and again if you reload or reset it):

```
https://cdn.jsdelivr.net/npm/mermaid@12.0.0/dist/mermaid.min.js
```

As with any web request, jsDelivr (and the network it runs on) can see the IP
address the request comes from, the standard request headers, and the file
requested. **The request contains no diagram, no file name, and no identifier of
you or your device**, and we do not add cookies, tracking parameters or
analytics to it. jsDelivr's own privacy policy governs that request:
<https://www.jsdelivr.com/terms/privacy-policy>.

Two related cases, both started by you:

- **Exported HTML.** An exported `.html` file embeds the same jsDelivr link, so
  it fetches mermaid when you open it in a browser. Exports of `.mmd`, `.json`
  and `.svg` never touch the network.
- **Browser fallback.** The temporary preview page described above also fetches
  mermaid from jsDelivr when you open it in your browser.

If your device has no internet connection, the app still starts, still builds
diagrams, and still exports every format — only the live preview is unavailable.

## What the app does not do

- No accounts, sign-in, or cloud sync.
- No background connections, update checks, or phoning home.
- No advertising, profiling, or third-party analytics or crash reporting.
- No access to your files beyond the ones you explicitly open or save.

## Children's privacy

The app collects no personal information from anyone, including children under
13. Nothing needs to be requested or deleted on their behalf.

## Microsoft Store

If you installed Diagram Maker from the Microsoft Store, Microsoft handles the
download, licensing and any Store-related data (for example a purchase record)
under the Microsoft Privacy Statement: <https://privacy.microsoft.com/privacystatement>.
That is between you and Microsoft; we receive no personal information from it.

## Your rights and deleting your data

Because we hold no data about you, there is nothing for us to disclose, correct,
export or erase on request. To remove everything the app has stored on your
device, uninstall it and delete any diagram, export or temporary preview files
you created.

## Open source

Diagram Maker is released under the MIT licence. Its source is public, so the
claims above can be verified: <https://github.com/faizal2007/mermaid-builder>.

## Changes to this policy

If a future version of the app changes how it handles data, this policy will be
updated and the effective date above will change before that version is released.

## Contact

Questions about this policy or about privacy in Diagram Maker:

**Mermaid Builder** — <mermaid-builder@geekdo.me>
