"""
Settings › Location tab: where the greenhouse is, for the outdoor weather and
for sunrise and sunset (which decide when the grow light may run).

Find a town (Open-Meteo's geocoding, ``core/places.py``) or type the
latitude and longitude. Saving stores the location in the database; the
weather collector reads it before every fetch, and this tab fetches the new
place's weather straight away, so Reports › Outdoor weather switches over
without restarting anything. Optionally the dashboard's time zone follows
the new place.
"""
import streamlit as st

from core import places
from ui import save_preferences

RESULTS_KEY = "location_results"
NOTICE_KEY = "location_notice"  # shown once, after the rerun that follows a save


def fetch_now() -> bool:
    """Fetch and store the weather for the location just saved (the collector would within 15 minutes)."""
    from services.weather_collector import collect_once

    return collect_once()


def use(place: dict, follow_zone: bool) -> None:
    """Save a place, optionally switch the dashboard's time zone, and fetch its weather now."""
    if not places.save(place):
        st.error("The location couldn't be saved.", icon=":material/error:")
        return
    if follow_zone and place.get("timezone"):
        st.session_state["timezone"] = "Local"
        st.session_state["timezone_name"] = place["timezone"]
        save_preferences()
    with st.spinner(f"Fetching the weather for {place['name']}…"):
        fetched = fetch_now()
    st.session_state.pop(RESULTS_KEY, None)
    st.session_state[NOTICE_KEY] = (
        f"Location set to {place['name']}. " + ("The outdoor weather is updated." if fetched else
                                                  "Its weather will appear within 15 minutes."))


def zone_choice(place: dict) -> bool:
    """Offer to show the dashboard's times in the place's time zone when it differs."""
    zone = place.get("timezone")
    if not zone or zone == st.session_state.get("timezone_name"):
        return False
    return st.checkbox(f"Also show the dashboard's times in {zone}", value=True,
                       help="Watering times follow the controller's own clock setting and don't change.")


def render() -> None:
    """Draw this section (called by its tabbed page)."""
    notice = st.session_state.pop(NOTICE_KEY, None)
    if notice:
        st.success(notice, icon=":material/check_circle:")
    current = places.current()
    st.markdown("The location is used for the outdoor weather and for sunrise and sunset, which decide "
                "when the grow light may run.")
    if current:
        with st.container(border=True):
            st.markdown(f":material/location_on: **{current['name']}**")
            source = "chosen here" if current["source"] == "dashboard" else "from the installer's settings"
            st.caption(f"{current['latitude']:.4f}, {current['longitude']:.4f} · {source}")
    else:
        st.warning("No location is set yet, so there is no outdoor weather.", icon=":material/location_off:")

    st.markdown("#### Change the location")
    with st.form("find_place", border=False):
        query = st.text_input("Town, postcode or address", placeholder="e.g. Sparks, NV · 89431 · Leeds, UK")
        if st.form_submit_button("Find", icon=":material/search:"):
            st.session_state[RESULTS_KEY] = places.search(query)
            if not st.session_state[RESULTS_KEY]:
                st.warning("No place found by that name (or no internet connection). Try another spelling, "
                           "or enter the latitude and longitude below.", icon=":material/search_off:")

    results = st.session_state.get(RESULTS_KEY) or []
    if results:
        index = st.radio("Choose the right place", range(len(results)),
                         format_func=lambda i: f"{results[i]['name']} ({results[i]['latitude']:.2f}, "
                                               f"{results[i]['longitude']:.2f})")
        follow_zone = zone_choice(results[index])
        if st.button("Use this location", type="primary", icon=":material/check:"):
            use(results[index], follow_zone)
            st.rerun()

    with st.expander("Enter the latitude and longitude instead"):
        with st.form("coordinates", border=False):
            name = st.text_input("Name", value="My greenhouse")
            latitude = st.number_input("Latitude", -90.0, 90.0, value=current["latitude"] if current else 0.0,
                                       format="%.4f", help="North is positive, south negative.")
            longitude = st.number_input("Longitude", -180.0, 180.0,
                                        value=current["longitude"] if current else 0.0, format="%.4f",
                                        help="East is positive, west negative.")
            if st.form_submit_button("Use these coordinates", icon=":material/check:"):
                use({"name": name.strip() or f"{latitude:.4f}, {longitude:.4f}", "latitude": latitude,
                     "longitude": longitude, "timezone": None}, follow_zone=False)
                st.rerun()
