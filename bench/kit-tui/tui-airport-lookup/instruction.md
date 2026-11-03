I book a lot of trips and keep forgetting airport codes. Make me a quick Textual lookup: I type
part of a code, airport name, city or country and it lists what matches; when I move to one it
shows me the details. I'd also like to star the airports I use all the time. The airport list
is in `airports.csv` in the folder.

## Contract

- `lookup.py` defines `class LookupApp(textual.app.App)` with
  `__init__(self, data_path, favorites_path)`; `python lookup.py` runs it with the defaults
  `airports.csv` and `favorites.json`.
- The data file is a UTF-8 CSV with header `code,name,city,country`.
- An `Input` with id `query`. As you type, a `ListView` with id `results` shows the airports
  where the trimmed query is a case-insensitive substring of the code, name, city or country —
  the first 50 such matches at most. A query with no matches shows an empty list. (What an empty
  query shows is up to you.)
- Each result is a `ListItem` whose text includes the airport's code and name.
- When a result is highlighted, a widget with id `detail` shows that airport's code, name, city
  and country.
- With the results list focused, `f` toggles the highlighted airport as a favourite. Favourites
  are stored in the JSON file at `favorites_path` as a list of airport codes, saved after every
  change (a missing file means no favourites). Favourite results show a `★` in their list item;
  others don't.
