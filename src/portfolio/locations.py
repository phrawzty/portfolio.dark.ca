"""Portfolio-owned places and interactive, cached location lookup."""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time
import tomllib
import unicodedata
from urllib.error import URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import tomlkit

from portfolio.errors import PortfolioError, UserCancelled

ATTRIBUTION = "Search data © OpenStreetMap contributors (ODbL), via Nominatim."
USER_AGENT = "portfolio.dark.ca/1.0 (https://github.com/phrawzty/portfolio.dark.ca)"


def normalized(value):
    decomposed = unicodedata.normalize("NFKD", value)
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).casefold().split())


def checked_coordinates(lat, lng):
    try:
        if isinstance(lat, bool) or isinstance(lng, bool):
            raise ValueError()
        lat, lng = float(lat), float(lng)
        if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
            raise ValueError()
    except (TypeError, ValueError, OverflowError) as error:
        raise PortfolioError("Invalid coordinates: supply latitude -90…90 and longitude -180…180") from error
    return lat, lng


def checked_country_code(value):
    code = value.strip().lower() if isinstance(value, str) else ""
    if not re.fullmatch(r"[a-z]{2}", code):
        raise PortfolioError("Supply a two-letter country code, such as br or fr")
    return code


def place_id(name, country_code):
    city = re.sub(r"[^a-z0-9]+", "-", normalized(name.split(",")[0])).strip("-")
    if not city:
        raise PortfolioError("Use a city name in Latin letters to generate its ID, or supply --id")
    return f"{city}-{checked_country_code(country_code)}"


def map_coordinates(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname not in ("www.openstreetmap.org", "openstreetmap.org"):
        raise PortfolioError("Use an OpenStreetMap URL containing #map=zoom/latitude/longitude")
    match = re.search(r"(?:^|&)map=[^/]+/(-?[\d.]+)/(-?[\d.]+)(?:&|$)", parsed.fragment)
    if not match:
        raise PortfolioError("The map URL must include #map=zoom/latitude/longitude")
    return checked_coordinates(*match.groups())


def ask(question, default=""):
    value = input(question + (f" [{default}]" if default else "") + ": ").strip()
    return value or default


class Locations:
    def __init__(self, root, settings):
        self.root = Path(root)
        self.path = self.root / "data/places.toml"
        self.settings = settings.get("geocoding", {})

    def places(self, validate=True):
        document = tomllib.loads(self.path.read_text()) if self.path.exists() else {}
        entries = document.get("place", [])
        if not isinstance(entries, list) or not all(isinstance(p, dict) for p in entries):
            raise PortfolioError(f"{self.path}: expected [[place]] entries")
        if validate:
            self.validate(entries)
        return entries

    def validate(self, entries):
        seen = set()
        for entry in entries:
            ident = entry.get("id", "")
            if not isinstance(ident, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", ident):
                raise PortfolioError(f"{self.path}: missing or invalid place ID {ident!r}")
            if ident in seen:
                raise PortfolioError(f"{self.path}: duplicate place ID {ident!r}")
            seen.add(ident)
            if not isinstance(entry.get("name"), str) or not entry["name"].strip():
                raise PortfolioError(f"Place {ident}: name is required")
            try:
                checked_coordinates(entry.get("lat"), entry.get("lng"))
            except PortfolioError as error:
                raise PortfolioError(f"Place {ident}: {error}") from error

    def get(self, ident):
        match = next((entry for entry in self.places() if entry["id"] == ident), None)
        if match is None:
            raise PortfolioError(f"Unknown place reference {ident!r}; select or add it with 'portfolio place'")
        return match

    def matches(self, name):
        query = normalized(name)
        entries = self.places()
        exact = [p for p in entries if normalized(p["name"]) == query or p["id"] == name]
        return exact or [p for p in entries if normalized(p["name"]).startswith(query + ",")]

    def save(self, name, lat, lng, ident=None, country_code=None):
        name = name.strip()
        if not name:
            raise PortfolioError("Place name is required")
        lat, lng = checked_coordinates(lat, lng)
        # Maintenance must be able to repair an entry with missing coordinates.
        entries = self.places(validate=False)
        existing = next((p for p in entries if p["id"] == ident), None) if ident else None
        if ident is None:
            matches = [p for p in entries if normalized(p["name"]) == normalized(name)]
            if len(matches) > 1:
                raise PortfolioError("Ambiguous place name; supply --id to update a specific place")
            existing = matches[0] if matches else None
            ident = existing["id"] if existing else place_id(name, country_code)
            if not existing and any(p["id"] == ident for p in entries):
                raise PortfolioError(f"Place ID {ident!r} already exists; select that place or use --id to distinguish it")
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", ident):
            raise PortfolioError("Place IDs must use lowercase letters, digits, hyphens or underscores")
        document = tomlkit.parse(self.path.read_text()) if self.path.exists() else tomlkit.document()
        places = document.get("place", tomlkit.aot())
        target = next((p for p in places if p["id"] == ident), None)
        if target is None:
            target = tomlkit.table()
            places.append(target)
        target.update(id=ident, name=name, lat=lat, lng=lng)
        document["place"] = places
        self.validate(places)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".toml.tmp")
        temporary.write_text(tomlkit.dumps(document))
        temporary.replace(self.path)
        return dict(target)

    def search(self, query):
        """Only called by an explicit interactive submission, never by builds."""
        endpoint = self.settings.get("endpoint", "https://nominatim.openstreetmap.org/search")
        if urlparse(endpoint).scheme != "https":
            raise PortfolioError("Geocoding endpoint must use HTTPS")
        cache = self.root / ".portfolio/geocoding"
        cache.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha256((endpoint + "\n" + normalized(query)).encode()).hexdigest()
        cached = cache / (key + ".json")
        # A shared lock and persisted timestamp also rate-limit separate CLI processes.
        with (cache / "requests.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if cached.exists():
                return json.loads(cached.read_text())
            stamp = cache / "last-request"
            last = float(stamp.read_text()) if stamp.exists() else 0
            time.sleep(max(0, 1.1 - (time.time() - last)))
            parameters = urlencode({"q": query, "format": "jsonv2", "limit": 5, "addressdetails": 1, "accept-language": "en"})
            request = Request(endpoint + "?" + parameters, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            stamp.write_text(str(time.time()))
            try:
                with urlopen(request, timeout=15) as response:
                    results = json.load(response)
                if not isinstance(results, list):
                    raise ValueError("expected a result list")
                for result in results:
                    checked_coordinates(result.get("lat"), result.get("lon"))
                    if not isinstance(result.get("display_name"), str):
                        raise ValueError("missing result name")
            except (URLError, OSError, ValueError, TypeError, AttributeError) as error:
                raise PortfolioError(f"Location search unavailable: {error}") from error
            cached.write_text(json.dumps(results, ensure_ascii=False) + "\n")
            return results

    def choose(self, entries):
        for index, entry in enumerate(entries, 1):
            print(f"  {index}. {entry['name']} ({entry['lat']}, {entry['lng']})")
        while True:
            choice = ask("Place number, or Enter to cancel")
            if not choice:
                raise UserCancelled()
            if choice.isdigit() and 1 <= int(choice) <= len(entries):
                return entries[int(choice) - 1]
            print("Choose one of the listed numbers.")

    def save_new(self, default_name, lat, lng, country_code=None):
        while True:
            name = ask("Save place name", default_name)
            matches = [p for p in self.places() if normalized(p["name"]) == normalized(name)]
            if not matches:
                while True:
                    try:
                        country_code = checked_country_code(country_code or ask("Two-letter country code (e.g. br, fr)"))
                        break
                    except PortfolioError as error:
                        print(error)
                        country_code = None
                place = self.save(name, lat, lng, country_code=country_code)
                print(f"Added {place['name']}.")
                return place
            if ask("That name is already registered. Use its saved location?", "y").casefold() in ("y", "yes"):
                return matches[0] if len(matches) == 1 else self.choose(matches)

    def resolve(self, name):
        name = name.strip()
        if normalized(name) in ("virtual", "online"):
            return None
        if not name:
            raise PortfolioError("Location is required")
        matches = self.matches(name)
        if len(matches) == 1:
            print(f"Selected {matches[0]['name']}.")
            return matches[0]
        if not sys.stdin.isatty():
            reason = "Ambiguous" if matches else "Unknown"
            raise PortfolioError(f"{reason} place {name!r}; run in a terminal to select/add it, or use 'portfolio place' first")
        if matches:
            print("Choose the location you mean:")
            return self.choose(matches)
        query = name
        while True:
            print(f"Looking up {query}…\n{ATTRIBUTION}")
            try:
                results = self.search(query)
            except PortfolioError as error:
                print(error)
                results = []
            selected = None
            if len(results) == 1:
                result = results[0]
                kind = result.get("addresstype") or result.get("type") or "place"
                print(f"Found: {result['display_name']} · {kind} ({result['lat']}, {result['lon']})")
                if ask("Use this place?", "y").casefold() in ("y", "yes"):
                    selected = result
            elif results:
                print("Choose a search result (Enter for other options):")
                try:
                    selected = self.choose([dict(r, name=f"{r['display_name']} · {r.get('addresstype') or r.get('type') or 'place'}", lng=r["lon"]) for r in results])
                except UserCancelled:
                    pass
            else:
                print("No suitable search results.")
            if selected:
                return self.save_new(name, selected["lat"], selected["lon"], selected.get("address", {}).get("country_code"))
            while True:
                action = ask("Search again [s], paste OSM URL [u], enter coordinates [c], or cancel [q]", "s").casefold()
                if action in ("q", "quit"):
                    raise UserCancelled()
                if action == "s":
                    query = ask("Search place", query)
                    # A refined query may resolve to a known local place.
                    matches = self.matches(query)
                    if matches:
                        return matches[0] if len(matches) == 1 else self.choose(matches)
                    break
                try:
                    if action == "u":
                        lat, lng = map_coordinates(ask("OpenStreetMap URL"))
                    elif action == "c":
                        lat, lng = checked_coordinates(ask("Latitude"), ask("Longitude"))
                    else:
                        print("Choose s, u, c, or q.")
                        continue
                    return self.save_new(name, lat, lng)
                except PortfolioError as error:
                    print(error)
