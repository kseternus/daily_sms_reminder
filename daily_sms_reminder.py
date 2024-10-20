from __future__ import print_function

import json
import time
import math
import pickle
import datetime
import requests
import threading
import pywhatkit
import os.path
from dateutil import parser
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# If modifying these SCOPES, delete the file token.pickle.
SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']

# Please enter your country phone prefix here
phone_prefix = '+48'
user_data_file = 'user_data_sms.json'
timeout = 0


def kelvin_to_celsius(temp):
    return temp - 273.15


def cardinal_direction(wind_deg):
    val = math.floor((wind_deg / 22.5) + 0.5)
    directions = [
        'N', 'NNE', 'NE', 'ENE', 'E', 'ESE',
        'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW',
        'W', 'WNW', 'NW', 'NNW'
    ]
    return directions[val % 16]


def calendar_events():
    """Fetch upcoming events from the Google Calendar API for today."""
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    service = build('calendar', 'v3', credentials=creds)
    now = datetime.datetime.utcnow().isoformat() + 'Z'  # 'Z' indicates UTC time
    end_of_day = (datetime.datetime.utcnow() + datetime.timedelta(days=1)).isoformat() + 'Z'

    events_result = service.events().list(
        calendarId='primary',
        timeMin=now,
        timeMax=end_of_day,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = events_result.get('items', [])

    if not events:
        return []

    upcoming_events = []
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        try:
            # Use dateutil.parser to parse the date string
            event_time = parser.isoparse(start).strftime('%H:%M')
        except ValueError:
            event_time = 'Unknown time'

        event_summary = event.get('summary', 'No Title')
        upcoming_events.append(f'{event_time}: {event_summary}')

    return upcoming_events


def load_user_data():
    """Load user data from JSON file."""
    try:
        with open(user_data_file, 'r') as file:
            data = file.read().strip()  # Read and strip any whitespace
            if not data:  # If the file is empty, return an empty list
                return []
            return json.loads(data)
    except (FileNotFoundError, json.JSONDecodeError):
        # If file does not exist or contains invalid JSON, return an empty list
        return []


def save_user_data(user_data):
    """Save user data to JSON file."""
    with open(user_data_file, 'w') as file:
        json.dump(user_data, file, indent=4)


def add_user_data():
    """Add a new user's data."""
    # Clear the existing data in the file
    with open(user_data_file, 'w') as file:
        file.write('[]')  # Write an empty list to the file to clear it

    # Proceed with adding the new user data
    name = input('Enter your name: ').capitalize()
    city = input('Enter your city: ').capitalize()
    phone = phone_prefix + input('Enter your phone number: ')
    time_str = input('Enter time for daily message (HH:MM in 24-hour format): ')

    user_data = load_user_data()
    user_data.append({
        'name': name,
        'city': city,
        'phone': phone,
        'time': time_str
    })
    save_user_data(user_data)
    print('User data saved successfully.')


def forecast(city):
    """Fetch weather information for a given city."""
    base_url = 'http://api.openweathermap.org/data/2.5/weather?'
    api_key = 'secret api key from openweathermap ;)'
    url = f"{base_url}appid={api_key}&q={city}"

    response = requests.get(url).json()

    if response.get('cod') != 200:
        print('City not found. Please check the name and try again.')
        return None

    current_time = datetime.datetime.now().strftime('%H:%M')
    date_now = datetime.datetime.utcfromtimestamp(response['dt']).strftime('%Y-%m-%d')
    sunrise = datetime.datetime.utcfromtimestamp(response['sys']['sunrise']).strftime('%H:%M:%S')
    sunset = datetime.datetime.utcfromtimestamp(response['sys']['sunset']).strftime('%H:%M:%S')
    description = response['weather'][0]['description']
    temp_celsius = kelvin_to_celsius(response['main']['temp'])  # Convert from Kelvin to Celsius
    temp_feels_like = kelvin_to_celsius(response['main']['feels_like'])
    pressure = response['main']['pressure']
    humidity = response['main']['humidity']
    wind_speed = response['wind']['speed']
    wind_deg = response['wind']['deg']
    visibility = response.get('visibility', 0)

    weather = (f'Time & date: {current_time}, {date_now}\n'
               f'Weather in {city.capitalize()}:\n'
               f'{description.capitalize()}\n'
               f'Temperature: {temp_celsius:.1f} °C\n'
               f'Feels like: {temp_feels_like:.1f} °C\n'
               f'Sunrise: {sunrise}, Sunset: {sunset}\n'
               f'Pressure: {pressure} hPa\n'
               f'Humidity: {humidity}%\n'
               f'Wind: {wind_speed} m/s {cardinal_direction(wind_deg)}\n'
               f'Visibility: {visibility / 1000:.1f} km\n')

    return weather


def create_message(name, city):
    """Create a weather and events message for the user."""
    weather_info = forecast(city)
    events_info = calendar_events()

    if weather_info:
        sms = (f'Good morning, {name}!\n'
               f'Here is your daily information and reminders:\n\n'
               f'{weather_info}\n')

        if events_info:
            sms += 'Upcoming Events Today:\n' + '\n'.join(events_info) + '\n'
        else:
            sms += 'No upcoming events today.\n'

        return sms
    else:
        print('Weather information could not be retrieved.')
        return None


def wait_for_exit_command():
    """Wait for the user to type 'exit' to stop the program."""
    while True:
        command = input("Type 'exit' to quit the program: ").strip().lower()
        if command == 'exit':
            print('Exiting the program...')
            break


def send_message_if_time_matches():
    """Check if the current time matches the scheduled time and send the message."""
    current_time = datetime.datetime.now().strftime('%H:%M')
    user_data = load_user_data()

    for user in user_data:
        if user['time'] == current_time:
            sms = create_message(user['name'], user['city'])
            if sms:
                try:
                    pywhatkit.sendwhatmsg_instantly(user['phone'], sms, wait_time=6, tab_close=True)
                    print(f"Message sent to {user['phone']} for {user['name']}.")
                except Exception as e:
                    print(f"Failed to send message to {user['phone']}: {e}")


# Add user data if necessary
add_user = input('Would you like to add a new user? (yes/no): ').strip().lower()
if add_user == 'yes':
    add_user_data()

# Create a separate thread for waiting for the 'exit' command
exit_thread = threading.Thread(target=wait_for_exit_command, daemon=True)
exit_thread.start()

# Periodically check if it's time to send a message
try:
    while exit_thread.is_alive():
        send_message_if_time_matches()
        # Wait 60 seconds before checking again
        time.sleep(60)
except KeyboardInterrupt:
    print('\nProgram terminated by user.')

# Ensure the exit thread completes before fully exiting
exit_thread.join()
