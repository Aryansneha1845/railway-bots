import requests

h = {
    'x-rapidapi-host': 'irctc1.p.rapidapi.com',
    'x-rapidapi-key': '3e1ae476b9msh23fa56ceb864394p189efcjsn0608a7111b65'
}

tests = [
    ('LIVE1',  'https://irctc1.p.rapidapi.com/api/v1/liveTrainStatus',          {'trainNo': '22177', 'startDay': '1'}),
    ('LIVE2',  'https://irctc1.p.rapidapi.com/api/v1/getTrainLiveStatus',       {'trainNo': '22177', 'startDay': '1'}),
    ('LIVE3',  'https://irctc1.p.rapidapi.com/api/v1/trainRunningStatus',       {'trainNo': '22177', 'startDay': '1'}),
    ('LIVE4',  'https://irctc1.p.rapidapi.com/api/v2/liveTrainStatus',          {'trainNo': '22177', 'startDay': '1'}),
    ('LIVE5',  'https://irctc1.p.rapidapi.com/api/v2/getTrainLiveStatus',       {'trainNo': '22177', 'startDay': '1'}),
    ('LIVE6',  'https://irctc1.p.rapidapi.com/api/v1/getRunningStatus',         {'trainNo': '22177', 'startDay': '1'}),
    ('LIVE7',  'https://irctc1.p.rapidapi.com/api/v3/getRunningStatus',         {'trainNo': '22177', 'startDay': '1'}),
    ('COACH1', 'https://irctc1.p.rapidapi.com/api/v1/getTrainCoach',            {'trainNo': '22177'}),
    ('COACH2', 'https://irctc1.p.rapidapi.com/api/v1/getCoachPosition',         {'trainNo': '22177'}),
    ('COACH3', 'https://irctc1.p.rapidapi.com/api/v1/trainCoach',               {'trainNo': '22177'}),
    ('BETWEEN','https://irctc1.p.rapidapi.com/api/v1/trainBetweenStations',     {'fromStationCode': 'CSMT', 'toStationCode': 'NDLS', 'dateOfJourney': '20260609'}),
]

for name, url, params in tests:
    try:
        r = requests.get(url, headers=h, params=params, timeout=10)
        print(f'{name}: {r.status_code} {r.text[:150]}')
    except Exception as e:
        print(f'{name}: ERROR {e}')
    print()
