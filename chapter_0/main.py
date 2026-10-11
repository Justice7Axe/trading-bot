import requests
import json
from config import host_url
from login import fn_au10001 as get_token

# 종목정보 리스트
def fn_ka10099(token, data, cont_yn='N', next_key=''):
	# 1. 요청할 API URL
	endpoint = '/api/dostk/stkinfo'
	url =  host_url + endpoint

	# 2. header 데이터
	headers = {
		'Content-Type': 'application/json;charset=UTF-8', # 컨텐츠타입
		'authorization': f'Bearer {token}', # 접근토큰
		'cont-yn': cont_yn, # 연속조회여부
		'next-key': next_key, # 연속조회키
		'api-id': 'ka10099', # TR명
	}

	# 3. http POST 요청
	response = requests.post(url, headers=headers, json=data)

	list = response.json()['list']

	print(json.dumps(list, indent=4, ensure_ascii=False))

# 실행 구간
if __name__ == '__main__':
	# 1. 토큰 설정
	MY_ACCESS_TOKEN = get_token() # 접근토큰

	# 2. 요청 데이터
	params = {
		'mrkt_tp': '0', # 시장구분 0:코스피,10:코스닥,3:ELW,8:ETF,30:K-OTC,50:코넥스,5:신주인수권,4:뮤추얼펀드,6:리츠,9:하이일드
	}

	# 3. API 실행
	fn_ka10099(token=MY_ACCESS_TOKEN, data=params)