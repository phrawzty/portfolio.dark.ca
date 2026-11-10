"""Location authoring uses explicit confirmation; all builds remain offline."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError

from portfolio.cli import Portfolio, PortfolioError, UserCancelled, parser
from portfolio.locations import Locations, checked_coordinates, place_id

SOURCE = Path(__file__).resolve().parents[1]
RESULT = {"display_name": "Warsaw, Masovian Voivodeship, Poland", "lat": "52.229263", "lon": "21.01181", "address": {"country_code": "pl"}}


class LocationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "data").mkdir()
        (self.root / "zola.toml").write_text('base_url = "https://example.com"\n')
        (self.root / "portfolio.toml").write_text("")
        self.locations = Locations(self.root, {})
        self.locations.save("Paris, France", 48.856614, 2.352222, "paris-fr")
        self.project = Portfolio(self.root)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()

    def tearDown(self):
        self.output.__exit__(None, None, None)
        self.temporary.cleanup()

    def test_known_name_or_city_is_local_and_case_insensitive(self):
        with patch("portfolio.locations.urlopen", side_effect=AssertionError("Network forbidden")):
            for name in ("paris, france", " PARIS ", "paris-fr"):
                self.assertEqual(self.locations.resolve(name)["id"], "paris-fr")

    def test_ambiguous_local_name_requires_a_selection(self):
        self.locations.save("Paris, Texas, USA", 33.66, -95.55, "paris-tx-us")
        with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", side_effect=["bad", "2"]), patch.object(Locations, "search", side_effect=AssertionError()):
            self.assertEqual(self.locations.resolve("Paris")["id"], "paris-tx-us")
        with patch("sys.stdin.isatty", return_value=False), self.assertRaisesRegex(PortfolioError, "Ambiguous"):
            self.locations.resolve("Paris")

    def test_add_unknown_location_during_new_appearance(self):
        args = parser().parse_args(["new", "--title", "Supply chains", "--event", "DevOpsDays Warsaw",
                                   "--date", "2030-11-23", "--location", "Warsaw, Poland"])
        with patch("sys.stdin.isatty", return_value=True), patch.object(Locations, "search", return_value=[RESULT]) as search, patch("builtins.input", side_effect=["y", ""]):
            ident = self.project.new(args)
        extra = self.project.appearance(ident)[1]["extra"]
        self.assertNotIn("location", extra)
        self.assertNotIn("latitude", extra)
        self.assertEqual(extra["place"], "warsaw-pl")
        self.assertEqual(self.project.location_label(extra), "Warsaw, Poland")
        self.assertEqual(self.project.coordinates(extra), (52.229263, 21.01181))
        search.assert_called_once_with("Warsaw, Poland")
        with patch.object(Locations, "search", side_effect=AssertionError()):
            self.assertEqual(self.locations.resolve("Warsaw, Poland")["id"], extra["place"])

    def test_multiple_search_results_are_not_accepted_automatically(self):
        other = dict(RESULT, display_name="Warsaw, Indiana, USA", lat="41.24", lon="-85.85")
        with patch("sys.stdin.isatty", return_value=True), patch.object(Locations, "search", return_value=[other, RESULT]), patch("builtins.input", side_effect=["2", "Warsaw, Poland"]):
            place = self.locations.resolve("Warsaw")
        self.assertEqual((place["lat"], place["lng"]), (52.229263, 21.01181))

    def test_decline_result_and_refine_search(self):
        with patch("sys.stdin.isatty", return_value=True), patch.object(Locations, "search", return_value=[RESULT]) as search, patch("builtins.input", side_effect=["n", "s", "Paris, France"]):
            self.assertEqual(self.locations.resolve("Elsewhere")["id"], "paris-fr")
        self.assertEqual(search.call_count, 1)
        self.assertEqual(len(self.locations.places()), 1)

    def test_unavailable_search_and_invalid_url_retry_in_place(self):
        with patch("sys.stdin.isatty", return_value=True), patch.object(Locations, "search", side_effect=PortfolioError("Offline")), patch("builtins.input", side_effect=[
            "u", "https://example.com/", "u", "https://www.openstreetmap.org/#map=12/52.229263/21.01181", "", "pl",
        ]):
            place = self.locations.resolve("Warsaw, Poland")
        self.assertEqual(place["lat"], 52.229263)

    def test_no_results_and_invalid_manual_coordinates_retry_in_place(self):
        with patch("sys.stdin.isatty", return_value=True), patch.object(Locations, "search", return_value=[]), patch("builtins.input", side_effect=[
            "c", "nan", "21", "c", "52.229263", "21.01181", "", "Poland", "pl",
        ]):
            place = self.locations.resolve("Warsaw, Poland")
        self.assertEqual(place["lng"], 21.01181)

    def test_cancellation_or_noninteractive_unknown_does_not_create_content(self):
        args = parser().parse_args(["new", "--title", "Talk", "--event", "Event", "--date", "2030-01-01", "--location", "Unknown"])
        with patch("sys.stdin.isatty", return_value=True), patch.object(Locations, "search", return_value=[]), patch("builtins.input", return_value="q"), self.assertRaises(UserCancelled):
            self.project.new(args)
        with patch("sys.stdin.isatty", return_value=False), patch.object(Locations, "search", side_effect=AssertionError()), self.assertRaisesRegex(PortfolioError, "Unknown place"):
            self.project.new(args)
        self.assertFalse((self.root / "content").exists())
        self.assertEqual(len(self.locations.places()), 1)

    def test_virtual_has_no_reference_or_network(self):
        with patch.object(Locations, "search", side_effect=AssertionError()):
            for value in ("Virtual", "Online", "ONLINE"):
                self.assertIsNone(self.locations.resolve(value))
        self.assertIsNone(self.project.coordinates({"virtual": True}))
        self.assertEqual(self.project.location_label({"virtual": True}), "Online")

    def test_search_caches_responses_and_identifies_the_application(self):
        response = io.BytesIO(json.dumps([RESULT]).encode())
        with patch("portfolio.locations.urlopen", return_value=response) as network:
            self.assertEqual(self.locations.search("Warsaw, Poland"), [RESULT])
            self.assertEqual(self.locations.search("WARSAW, POLAND"), [RESULT])
        network.assert_called_once()
        request = network.call_args.args[0]
        self.assertIn("portfolio.dark.ca", request.get_header("User-agent"))
        self.assertIn("accept-language=en", request.full_url)

    def test_search_rate_limit_persists_between_instances_and_handles_failure(self):
        directory = self.root / ".portfolio/geocoding"
        directory.mkdir(parents=True)
        (directory / "last-request").write_text("100")
        with patch("portfolio.locations.time.time", return_value=100.4), patch("portfolio.locations.time.sleep") as sleep, patch("portfolio.locations.urlopen", side_effect=URLError("Unavailable")), self.assertRaisesRegex(PortfolioError, "unavailable"):
            Locations(self.root, {}).search("Unknown")
        self.assertAlmostEqual(sleep.call_args.args[0], 0.7)
        self.assertEqual((directory / "last-request").read_text(), "100.4")

    def test_malformed_response_is_rejected_and_not_cached(self):
        for result in ({}, [{"display_name": "Invalid", "lat": "nan", "lon": "0"}]):
            with self.subTest(result=result), patch("portfolio.locations.time.sleep"), patch("portfolio.locations.urlopen", return_value=io.BytesIO(json.dumps(result).encode())), self.assertRaisesRegex(PortfolioError, "unavailable"):
                self.locations.search("Unknown")
        self.assertFalse(list((self.root / ".portfolio/geocoding").glob("*.json")))

    def test_stable_id_survives_registry_name_and_label_changes(self):
        extra = {"place": "paris-fr"}
        before = self.project.coordinates(extra)
        self.locations.save("Paris, FR", *before, ident="paris-fr")
        self.assertEqual(self.project.location_label(extra), "Paris, FR")
        extra["location_label"] = "Paris · Venue"
        self.assertEqual(self.project.location_label(extra), "Paris · Venue")
        self.assertEqual(self.project.coordinates(extra), before)

    def test_generated_id_collisions_do_not_overwrite_places(self):
        first = self.locations.save("A-B, France", 1, 2, country_code="fr")
        with self.assertRaisesRegex(PortfolioError, "already exists"):
            self.locations.save("A B, France", 3, 4, country_code="fr")
        self.assertEqual(self.locations.get(first["id"])["lat"], 1)

    def test_id_uses_city_and_country_code_without_state_or_country_name(self):
        self.assertEqual(place_id("Rio de Janeiro, RJ, Brazil", "BR"), "rio-de-janeiro-br")
        self.assertEqual(place_id("Portland, OR, USA", "us"), "portland-us")
        self.assertEqual(place_id("Zürich, Switzerland", "ch"), "zurich-ch")
        for code in (None, "", "Brazil", "123"):
            with self.subTest(code=code), self.assertRaisesRegex(PortfolioError, "two-letter country"):
                place_id("Rio de Janeiro, RJ, Brazil", code)

    def test_rio_authoring_generates_the_existing_appearance_reference(self):
        result = {"display_name": "Rio de Janeiro, Southeast Region, Brazil", "lat": "-22.9110137", "lon": "-43.2093727", "address": {"country_code": "br"}}
        with patch("sys.stdin.isatty", return_value=True), patch.object(Locations, "search", return_value=[result]), patch("builtins.input", side_effect=["y", ""]):
            place = self.locations.resolve("Rio de Janeiro, RJ, Brazil")
        self.assertEqual(place["id"], "rio-de-janeiro-br")
        self.assertEqual(place["name"], "Rio de Janeiro, RJ, Brazil")

    def test_invalid_coordinates_and_unknown_references_fail(self):
        for lat, lng in ((None, 0), (True, 0), ("nan", 0), (0, "inf"), (91, 0), (0, -181)):
            with self.subTest(lat=lat, lng=lng), self.assertRaisesRegex(PortfolioError, "Invalid coordinates"):
                checked_coordinates(lat, lng)
        with self.assertRaisesRegex(PortfolioError, "Unknown place reference"):
            self.project.coordinates({"place": "missing"})
        self.locations.path.write_text('[[place]]\nid = "paris-fr"\nname = "Paris"\n')
        with self.assertRaisesRegex(PortfolioError, "Place paris-fr: Invalid coordinates"):
            self.locations.places()

    def test_duplicate_registry_ids_are_invalid(self):
        content = self.locations.path.read_text()
        self.locations.path.write_text(content + "\n" + content)
        with self.assertRaisesRegex(PortfolioError, "duplicate place ID"):
            self.locations.places()

    def test_place_maintenance_updates_by_id(self):
        self.project.place("Paris, FR", "https://openstreetmap.org/#map=10/48.856614/2.352222", "paris-fr")
        self.assertEqual(len(self.locations.places()), 1)
        self.assertEqual(self.locations.get("paris-fr")["name"], "Paris, FR")

    def test_place_maintenance_can_repair_missing_coordinates(self):
        self.locations.path.write_text('[[place]]\nid = "paris-fr"\nname = "Paris"\n')
        self.project.place("Paris, France", ident="paris-fr", latitude=48.856614, longitude=2.352222)
        self.assertEqual(self.locations.get("paris-fr")["lat"], 48.856614)

    def test_renaming_a_search_result_does_not_overwrite_a_known_place(self):
        with patch("sys.stdin.isatty", return_value=True), patch.object(Locations, "search", return_value=[RESULT]), patch("builtins.input", side_effect=["y", "Paris, France", "y"]):
            place = self.locations.resolve("Warsaw")
        self.assertEqual(place["id"], "paris-fr")
        self.assertEqual(place["lat"], 48.856614)

    def test_non_latin_names_remain_distinct(self):
        first = self.locations.save("東京", 35.67, 139.65, ident="tokyo-jp")
        second = self.locations.save("大阪", 34.69, 135.50, ident="osaka-jp")
        self.assertEqual(self.locations.resolve("東京")["id"], first["id"])
        self.assertNotEqual(first["id"], second["id"])


class MigrationTests(unittest.TestCase):
    def test_existing_resolved_points_urls_and_display_names_are_preserved(self):
        project = Portfolio(SOURCE)
        before = json.loads((SOURCE / "tests/fixtures/map-before-locations.json").read_text())
        for row in before:
            with self.subTest(appearance=row["id"]):
                _, meta, _ = project.appearance(row["id"])
                extra = meta["extra"]
                self.assertEqual(meta["path"], row["id"])
                if row["id"] == "2025-08-16-devopsdays-rio-de-janeiro":
                    self.assertEqual(extra["place"], "rio-de-janeiro-br")
                    self.assertEqual(project.coordinates(extra), (-22.9110137, -43.2093727))
                self.assertEqual(project.location_label(extra), row["location"])
                if row["coordinates"] is not None:
                    self.assertEqual(list(project.coordinates(extra)), row["coordinates"])
                elif row["virtual"]:
                    self.assertIsNone(project.coordinates(extra))
        used = {meta["extra"]["place"] for _, meta, _ in project.appearances() if not meta["extra"].get("virtual")}
        self.assertEqual({place["id"] for place in project.places()}, used)


if __name__ == "__main__":
    unittest.main()
