# ADR-013: licensed pharmacies near a person, and how the person's location is handled

Status: accepted, 2026-11-21 (owner asked to use the patient's location for nearby pharmacies; Q-23
default approved: location used once per request and not stored, directions through the phone's maps
app, no stock claims).

## Context

The SFDA list of licensed pharmacies has 385 rows with a name, a phone number, a region and an
address. Checked on the real rows: the address is only **a city and a Saudi National Address short
code** (`Jeddah - JJMA3817`), never a street and never coordinates. The city is typed by hand, so one
city appears under several spellings (`Khobar`, `alkhabar`, `Alkhober`, `الخبر`), some rows have only a
code (`DMAI8220`) and a few have no city at all. Geocoding the addresses with OpenStreetMap would
therefore give one point per city, the same for every pharmacy in it.

## Decision

- **"Near" means by city, said plainly.** The API returns the cities whose centre is within the
  radius, nearest first, each with its licensed pharmacies; the distance is to the city centre, never
  to a pharmacy, and every response and screen says so. If no city is inside the radius it names the
  nearest one and how far it is. Pharmacies with no usable city, and pharmacies in a city that has no
  point yet, are **counted in the answer, not hidden**.
- **The city is cleaned with a small alias table** (`catalog/domain/pharmacies.py`) that joins only
  spellings that occur in the real list. A city not in the table keeps its own spelling.
- **City points come from a geocoder, once** (`pharmavique geocode-cities`): OpenStreetMap's Nominatim,
  one request a second, a clear User-Agent with no personal detail, only city names sent, answers
  stored with the exact request and time in `catalog.city_locations`, trust `unofficial_unverified`.
  A result outside a box around Saudi Arabia is refused. **A point that is more than 500 km from the
  median point of the other cities of the same region is not saved** and is listed: the first run put
  Al-Namas (Aseer) near Riyadh, a place of the same name, and this check caught it. Cities the geocoder
  cannot place are listed, not guessed.
- **The person's position is sent in the body of a POST** (`POST /v1/pharmacies/nearby`), not in a URL,
  so it cannot appear in an access log. It is used for one computation, never stored, never logged,
  never cached (`Cache-Control: no-store`, no shared cache), and the app asks for the foreground
  permission only and does not keep the position after the request. Without permission the app lists
  cities to choose from, and `GET /v1/pharmacies` searches by city, region or name with no position.
- **No claims.** Nothing says a pharmacy has a drug in stock, is open, or is the best choice. "Directions"
  are a search of the pharmacy's name and city in the phone's own maps app, since there is no
  coordinate to navigate to.
- The pharmacy rows stay where they are (the catalog's official-list rows, `official` trust); the
  parsing lives in the catalog and is published through `CatalogPharmacies`.

## Consequences

- Precision is the city. Inside Riyadh (136 pharmacies) the order is by name, not distance. Better
  needs the exact coordinates of each pharmacy, which the National Address short code could give
  through the national address service (an API with its own key and terms): Q-39.
- The city points are unreviewed geocoder output. Names that are also regions (Najran, Al Jouf, Bisha)
  may be a region's centre rather than the town's; a person who knows the places should look at the 33
  points once.
- Two cities have no point (`Alhafoof`, `Al-Namas`) and their pharmacies only appear in the city list
  and the search.
