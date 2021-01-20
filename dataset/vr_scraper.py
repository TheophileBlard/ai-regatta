from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities
from selenium.webdriver.common.action_chains import ActionChains

import json
from pathlib import Path
import time

import requests
from tqdm.auto import trange, tqdm



def process_browser_logs_for_network_events(logs):
    for entry in logs:
        log = json.loads(entry["message"])["message"]
        if (
            "Network.response" in log["method"]
            or "Network.request" in log["method"]
            or "Network.webSocket" in log["method"]
        ):
            yield log


class APIKeyGenerator:
    DEFAULT_DRIVER_PATH = Path.home() / "chromedriver"
    GAME_URL = "https://www.virtualregatta.com/en/offshore-game/"
    SLEEP_TIME = 10
    X_OFFSET, Y_OFFSET = 200, 200
    API_KEY_STR = "x-api-key"

    def __init__(self, chrome_driver_path=DEFAULT_DRIVER_PATH):
        if not chrome_driver_path.exists():
            raise ValueError(f"Path does not exist: `{chrome_driver_path}`")

        caps = DesiredCapabilities.CHROME
        # capabilities["loggingPrefs"] = {"performance": "ALL"}  # chromedriver < ~75
        caps["goog:loggingPrefs"] = {"performance": "ALL"}  # chromedriver 75+

        chrome_options = Options()
        chrome_options.add_argument("user-data-dir=selenium")
        chrome_options.headless = False
        self.driver = webdriver.Chrome(
            chrome_driver_path, options=chrome_options, desired_capabilities=caps
        )

    def get_new_key(self):
        print("Regenerating new key...")
        self.driver.get(self.GAME_URL)
        time.sleep(self.SLEEP_TIME)

        # Click on "Virtual Regatta" race
        game = self.driver.find_element_by_class_name("gameDiv")
        action = ActionChains(self.driver)
        action.move_to_element_with_offset(
            game, self.X_OFFSET, self.Y_OFFSET
        ).click().perform()
        time.sleep(self.SLEEP_TIME / 2)

        # Get network logs and search api key
        logs = self.driver.get_log("performance")
        api_key = self._get_api_key_from_logs(logs)
        if len(api_key) == 0:
            raise Exception("Failed to get API Key!")

        return api_key

    def __del__(self):
        pass
        # self.driver.close()

    def _get_api_key_from_logs(self, logs):
        logs = process_browser_logs_for_network_events(logs)
        for log in logs:
            if "headers" in log["params"]:
                if self.API_KEY_STR in log["params"]["headers"]:
                    return log["params"]["headers"][self.API_KEY_STR]
        return ""


class VRScraper:
    API_URL = "https://vro-api-client.prod.virtualregatta.com"
    MAX_RETRIES = 3

    def __init__(self, key_generator, player_id):
        self.key_generator = key_generator
        self.player_id = player_id
        self.curr_api_key = ""

    def get_player_list(self, race_id: int, num_players: int, page_size: int = 1000):
        ENDPOINT = "getlegranks"
        PAGE_NUM = (num_players // page_size) + 1
        PAYLOAD = {
            "race_id": str(race_id),
            "leg_num": "1",
            "user_id": self.player_id,
            "partition": "0",
            "value": "0",
            "members": "",
            "friends": [],
            # "page_number":"1",
            "page_size": str(page_size),
            "request_type": "1",
        }
        player_list = []  # sorted by rank
        for i in range(PAGE_NUM):
            PAYLOAD["page_number"] = str(i + 1)
            # print(PAYLOAD)
            ret = self._post_request(ENDPOINT, PAYLOAD)
            if ret == {}:
                print(ret)
                raise RuntimeError(f"Could not get player list for race_id={race_id}")
            player_list.extend(ret["res"]["rank"])

        return player_list

    def get_boat_infos(self, race_id: int, player_id: str):
        ENDPOINT = "getboatinfos"
        PAYLOAD = {
            "user_id": player_id,
            "race_id": str(race_id),
            "leg_num": "1",
            "infos": "bs,track",  # ,engine"
        }
        ret = self._post_request(ENDPOINT, PAYLOAD)
        return ret["res"]

    def get_boat_infos_bulk(self, race_id: int, player_ids):
        output = []
        for player_id in tqdm(player_ids):
            boat_infos = self.get_boat_infos(race_id, player_id)
            output.append(boat_infos)
        return output

    def get_race_list(self, min_id=0, max_id=1000):
        output = []
        for race_id in trange(min_id, max_id, desc="Downloading race list..."):
            try:
                player_list = self.get_player_list(race_id, 1, 1)
                if player_list:
                    p = player_list[0]
                    boat = self.get_boat_infos(race_id, p["_id"])
                    output.append((race_id, boat["bs"]["boat"]["label"]))
            except RuntimeError as e:
                print(e)
        return output

    def get_race_infos(self, race_id):
        ENDPOINT = "getboatinfos"
        PAYLOAD = {
            "user_id": self.player_id,
            "race_id": str(race_id),
            "leg_num": "1",
            "infos": "leg",
        }
        ret = self._post_request(ENDPOINT, PAYLOAD)
        return ret["res"]["leg"]

    def _post_request(self, endpoint: str, payload):
        url = f"{self.API_URL}/{endpoint}"
        for i in range(0, self.MAX_RETRIES):
            r = requests.post(
                url,
                json=payload,
                headers=self._get_request_headers(),
            )
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 403:
                self.curr_api_key = self.key_generator.get_new_key()
            else:
                print("Fatal error ?")
                continue
        return {}

    def _get_request_headers(self):
        if self.curr_api_key == "":
            self.curr_api_key = self.key_generator.get_new_key()
        return {
            "x-api-key": self.curr_api_key,
            "x-playerid": self.player_id,
        }
