CREATE TABLE d_actions (actionid TEXT PRIMARY KEY UNIQUE NOT NULL, actionname TEXT NOT NULL);
CREATE TABLE d_devices (deviceid TEXT PRIMARY KEY NOT NULL UNIQUE, devicename TEXT NOT NULL);
CREATE TABLE d_measures (measureid TEXT NOT NULL PRIMARY KEY UNIQUE, measurename TEXT NOT NULL, siunit TEXT, englishunit TEXT);
CREATE TABLE d_relays (relayid TEXT PRIMARY KEY UNIQUE NOT NULL, relayname TEXT NOT NULL);
CREATE TABLE "greenhouse_data" ( "measuredatetime" TEXT NOT NULL, "deviceid" TEXT NOT NULL, "measureid" TEXT NOT NULL, "value_001" NUMERIC NOT NULL, "value_002" NUMERIC, PRIMARY KEY("measuredatetime","deviceid","measureid"), FOREIGN KEY("deviceid") REFERENCES "d_devices"("deviceid") ON DELETE CASCADE ON UPDATE CASCADE, FOREIGN KEY("measureid") REFERENCES "d_measures"("measureid") ON DELETE CASCADE ON UPDATE CASCADE );
CREATE TABLE relay_conditions ( deviceid TEXT, relayid TEXT, condition TEXT, value TEXT, buffer TEXT, conditionname TEXT );
CREATE TABLE relay_conditions_default ( deviceid TEXT, relayid TEXT, condition TEXT, value TEXT, buffer TEXT, conditionname TEXT );
CREATE TABLE "relay_status" ( "actiontime" TEXT, "deviceid" TEXT, "relayid" TEXT, "actionid" TEXT );
CREATE TABLE weather_data (LATITUDE TEXT, LONGITUDE TEXT, TIMEZONE TEXT, MEASURE_DATE TEXT PRIMARY KEY ASC, ELEVATION NUM, TEMPERATURE NUM, APPARENT_TEMPERATURE NUM, RELATIVE_HUMIDITY NUM, PRECIPITATION NUM, RAIN NUM, SNOWFALL NUM, SHOWERS NUM, WEATHER_CODE INT, WIND_SPEED NUM, WIND_DIRECTION NUM, SUNRISE_TIME TEXT, SUNSET_TIME TEXT);
