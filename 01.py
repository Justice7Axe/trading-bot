# rest api
import requests

url = "https://api.upbit.com/v1/market/all"

resp = requests.get(url)
data = resp.json() #JSON
# print(data)
print(len(data))