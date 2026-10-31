#!/usr/bin/env python3
"""Oslo-skjerm: henter avganger (Entur) og vær (MET) og serverer skjermsiden på localhost.

Kun standardbiblioteket brukes, så ingen pip-installasjon trengs på Rock 4C+.
"""
import json
import os
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(BASE_DIR, "config.json"), encoding="utf-8") as f:
    CONFIG = json.load(f)

ENTUR_URL = "https://api.entur.io/journey-planner/v3/graphql"
MET_URL = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat}&lon={lon}"

AVGANGER_QUERY = """
query Avganger($id: String!, $antall: Int!, $tid: Int!) {
  stopPlace(id: $id) {
    name
    estimatedCalls(numberOfDepartures: $antall, timeRange: $tid) {
      expectedDepartureTime
      aimedDepartureTime
      realtime
      destinationDisplay { frontText }
      serviceJourney { journeyPattern { line { publicCode name transportMode } } }
    }
  }
}
"""

# Symbolkoder fra MET -> (emoji, norsk tekst). Nøkkelen er grunnkoden uten _day/_night.
SYMBOLER = {
    "clearsky": ("☀️", "Klarvær"),
    "fair": ("🌤️", "Lettskyet"),
    "partlycloudy": ("⛅", "Delvis skyet"),
    "cloudy": ("☁️", "Skyet"),
    "fog": ("🌫️", "Tåke"),
    "lightrain": ("🌦️", "Lett regn"),
    "rain": ("🌧️", "Regn"),
    "heavyrain": ("🌧️", "Kraftig regn"),
    "lightrainshowers": ("🌦️", "Regnbyger"),
    "rainshowers": ("🌧️", "Regnbyger"),
    "heavyrainshowers": ("🌧️", "Kraftige regnbyger"),
    "lightsleet": ("🌨️", "Lett sludd"),
    "sleet": ("🌨️", "Sludd"),
    "heavysleet": ("🌨️", "Kraftig sludd"),
    "lightsnow": ("🌨️", "Lett snø"),
    "snow": ("❄️", "Snø"),
    "heavysnow": ("❄️", "Kraftig snø"),
    "snowshowers": ("🌨️", "Snøbyger"),
}

LAAS = threading.Lock()
TILSTAND = {
    "stasjoner": {},      # stopp-id -> sist vellykkede avganger
    "vaer": None,
    "vaer_hentet": 0.0,
    "feil": [],
    "oppdatert": None,
}


def hent_json(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    with urllib.request.urlopen(req, timeout=15) as svar:
        return json.loads(svar.read().decode("utf-8"))


def siste_sondag(aar, maaned):
    dag = datetime(aar, maaned + 1, 1) - timedelta(days=1)
    while dag.weekday() != 6:
        dag -= timedelta(days=1)
    return dag


def oslo_tid(utc):
    """Gjør et UTC-tidspunkt om til norsk tid (CET/CEST, EU-regler for sommertid)."""
    sommer_start = siste_sondag(utc.year, 3).replace(hour=1, tzinfo=timezone.utc)
    sommer_slutt = siste_sondag(utc.year, 10).replace(hour=1, tzinfo=timezone.utc)
    timer = 2 if sommer_start <= utc < sommer_slutt else 1
    return utc.astimezone(timezone(timedelta(hours=timer)))


def beskriv_symbol(kode):
    if not kode:
        return "", ""
    base, _, tidspunkt = kode.partition("_")
    if base == "clearsky" and tidspunkt == "night":
        return "🌙", "Klarvær"
    if "thunder" in base:
        return "⛈️", "Torden"
    return SYMBOLER.get(base, ("🌡️", kode))


def hent_avganger(stopp):
    body = json.dumps({
        "query": AVGANGER_QUERY,
        "variables": {
            "id": stopp["id"],
            "antall": CONFIG["antall_avganger"],
            "tid": CONFIG["tidsvindu_sekunder"],
        },
    }).encode("utf-8")
    svar = hent_json(ENTUR_URL, data=body, headers={
        "Content-Type": "application/json",
        "ET-Client-Name": CONFIG["entur_client_name"],
    })
    if svar.get("errors"):
        raise RuntimeError(svar["errors"][0].get("message", "ukjent feil fra Entur"))
    sted = svar["data"]["stopPlace"]
    if sted is None:
        raise RuntimeError(f"fant ikke stoppested {stopp['id']}")

    avganger = []
    for call in sted["estimatedCalls"]:
        linje = call["serviceJourney"]["journeyPattern"]["line"]
        avganger.append({
            "linje": linje["publicCode"],
            "transport": linje["transportMode"],
            "retning": call["destinationDisplay"]["frontText"],
            "planlagt": call["aimedDepartureTime"],
            "forventet": call["expectedDepartureTime"],
            "sanntid": call["realtime"],
        })
    return {"id": stopp["id"], "navn": stopp["navn"], "avganger": avganger}


def hent_vaer():
    url = MET_URL.format(lat=CONFIG["lat"], lon=CONFIG["lon"])
    svar = hent_json(url, headers={"User-Agent": CONFIG["met_user_agent"]})
    serie = svar["properties"]["timeseries"]

    na_punkt = serie[0]
    na_symbol = na_punkt["data"].get("next_1_hours") or na_punkt["data"].get("next_6_hours") or {}
    emoji, tekst = beskriv_symbol(na_symbol.get("summary", {}).get("symbol_code"))

    i_dag = oslo_tid(datetime.now(timezone.utc)).date()
    temperaturer = []
    nedbor = 0.0
    for punkt in serie:
        tid = oslo_tid(datetime.fromisoformat(punkt["time"].replace("Z", "+00:00")))
        if tid.date() != i_dag:
            continue
        temperaturer.append(punkt["data"]["instant"]["details"]["air_temperature"])
        neste_time = punkt["data"].get("next_1_hours")
        if neste_time:
            nedbor += neste_time["details"].get("precipitation_amount", 0.0)

    timer = []
    for punkt in serie[0:10:2]:
        tid = oslo_tid(datetime.fromisoformat(punkt["time"].replace("Z", "+00:00")))
        symbol = punkt["data"].get("next_1_hours") or punkt["data"].get("next_6_hours") or {}
        t_emoji, _ = beskriv_symbol(symbol.get("summary", {}).get("symbol_code"))
        timer.append({
            "tid": tid.strftime("%H:%M"),
            "temp": punkt["data"]["instant"]["details"]["air_temperature"],
            "symbol": t_emoji,
        })

    return {
        "naa": {
            "temp": na_punkt["data"]["instant"]["details"]["air_temperature"],
            "symbol": emoji,
            "tekst": tekst,
        },
        "i_dag": {
            "hoyest": max(temperaturer) if temperaturer else None,
            "lavest": min(temperaturer) if temperaturer else None,
            "nedbor": round(nedbor, 1),
        },
        "timer": timer,
    }


def oppdater_avganger():
    feil = []
    for stopp in CONFIG["stopp"]:
        try:
            resultat = hent_avganger(stopp)
            resultat["navn"] = stopp["navn"]  # bruk navnet fra config, ikke fra API
            with LAAS:
                TILSTAND["stasjoner"][stopp["id"]] = resultat
        except Exception as e:  # beholder forrige gode data ved feil
            feil.append(f"{stopp['navn']}: {e}")
    return feil


def oppdater_vaer():
    if time.time() - TILSTAND["vaer_hentet"] < CONFIG["oppdater_vaer_sekunder"] and TILSTAND["vaer"]:
        return None
    try:
        vaer = hent_vaer()
    except Exception as e:
        return f"Vær: {e}"
    with LAAS:
        TILSTAND["vaer"] = vaer
        TILSTAND["vaer_hentet"] = time.time()
    return None


def oppdater_alt():
    feil = oppdater_avganger()
    vaerfeil = oppdater_vaer()
    if vaerfeil:
        feil.append(vaerfeil)
    with LAAS:
        TILSTAND["feil"] = feil
        TILSTAND["oppdatert"] = datetime.now(timezone.utc).isoformat()


def bakgrunn():
    while True:
        try:
            oppdater_alt()
        except Exception as e:
            print("Uventet feil ved oppdatering:", e, flush=True)
        time.sleep(CONFIG["oppdater_avganger_sekunder"])


def data_for_side():
    with LAAS:
        return {
            "stasjoner": [TILSTAND["stasjoner"][s["id"]] for s in CONFIG["stopp"] if s["id"] in TILSTAND["stasjoner"]],
            "vaer": TILSTAND["vaer"],
            "feil": list(TILSTAND["feil"]),
            "oppdatert": TILSTAND["oppdatert"],
        }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.join(BASE_DIR, "web"), **kwargs)

    def do_GET(self):
        if self.path.startswith("/api/data"):
            kropp = json.dumps(data_for_side(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(kropp)))
            self.end_headers()
            self.wfile.write(kropp)
            return
        super().do_GET()

    def log_message(self, format, *args):
        pass  # holder journal/logg stille; feil skrives fortsatt ut via print


if __name__ == "__main__":
    threading.Thread(target=bakgrunn, daemon=True).start()
    server = ThreadingHTTPServer((CONFIG["host"], CONFIG["port"]), Handler)
    print(f"Oslo-skjerm kjører på http://{CONFIG['host']}:{CONFIG['port']}", flush=True)
    server.serve_forever()
