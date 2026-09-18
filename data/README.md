The data folder
The website's collection comes from the British Museum repository. Every Monday, and whenever you edit one of the three files below, GitHub rebuilds the collection automatically. Each run writes `report.md`, which lists anything that needs your attention.
Files you edit
Open them in Excel, LibreOffice or Google Sheets. When saving from Excel, choose CSV UTF-8 so Kazakh and Mongolian letters survive. Then upload the file back to this folder on GitHub (Add file → Upload files).
categories.csv
One row per item. New items are added automatically, with a suggested category already filled in.
Column	What to do
category	Check or change. Use one or more of: Syrmaq, Tus Kiiz, Terme, Skins & Leather, Spindles, Craft Videos, Interviews, Behind The Scenes. Separate several with a semicolon.
household	Fill in if known.
maker	Fill in if known. Left blank, the site shows "Unavailable".
reviewed	Type "yes" once you've checked the row, to keep track of your progress.
notes	Anything you like; the site ignores it.
Other columns (title, keywords, participants_in_repository, suggested_category) are refreshed from the repository each time, so edits there are overwritten.
corrections.csv
One row per fix, for anything the repository has wrong. Columns: `unique_id` (for example 2021SG06-C04-1269), `field`, `value`, `note`.
field	Effect
credit	Replaces the photo credit
title_en, title_kk, title_mn	Replaces a title
description_en, description_kk, description_mn	Replaces a description
maker, household	Overrides categories.csv
place	Replaces the repository's place text
date, cultural_group	Replaces these details
frame_time	For videos: the moment used for the grid image, for example 0:45
hide	"yes" removes the item from the site
show_sensitive	"yes" shows an item the repository marks as culturally sensitive
places.csv
One row per place spelling found in the repository. To merge spellings (for example Tsagaannuur and Tsagaannur), give both rows the same `display_en`. Fill in `display_mn` for Mongolian.
Files not to edit
`items.json`, `report.md`, `cache.json` and the `media` folder are rewritten by each update.
