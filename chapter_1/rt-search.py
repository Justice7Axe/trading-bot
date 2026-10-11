import asyncio 
import websockets
import json
import sys
import requests
from datetime import datetime, timedelta, timezone
from config import socket_url, host_url
from login import fn_au10001 as get_token

# 한국 시간대 설정 (UTC+9)
KST = timezone(timedelta(hours=9))

# 콘솔 출력을 파일로도 저장하는 클래스 (시간 제한 및 필터링 기능 포함)
class TeeOutput:
	"""콘솔과 파일에 동시에 출력하는 클래스 (한국시간 08:50~16:00만 파일 저장)"""
	def __init__(self, console_file, log_file):
		self.console_file = console_file
		self.log_file = log_file
		self.last_update_time = None
		self.excluded_messages = ['Connection closed by the server']
	
	def is_trading_hours(self):
		"""한국시간 08:50 ~ 16:00인지 확인"""
		now_kst = datetime.now(KST)
		current_time = now_kst.time()
		start_time = datetime.strptime('08:50', '%H:%M').time()
		end_time = datetime.strptime('16:00', '%H:%M').time()
		return start_time <= current_time <= end_time
	
	def should_write_to_file(self, message):
		"""파일에 쓸지 여부 결정"""
		# 제외할 메시지 확인
		for excluded in self.excluded_messages:
			if excluded in message:
				return False
		# 거래 시간 확인
		return self.is_trading_hours()
	
	def write(self, obj):
		# 콘솔에는 항상 출력
		self.console_file.write(obj)
		self.console_file.flush()
		
		# 파일에는 조건에 맞을 때만 출력
		if self.should_write_to_file(obj):
			now_kst = datetime.now(KST)
			current_time_str = now_kst.strftime('%Y-%m-%d %H:%M:%S')
			
			# 업데이트 시간이 변경되었거나 첫 기록인 경우 시간 기록
			if self.last_update_time != current_time_str:
				self.log_file.write(f'\n[업데이트 시간: {current_time_str}]\n')
				self.last_update_time = current_time_str
			
			self.log_file.write(obj)
			self.log_file.flush()  # 즉시 파일에 쓰기
	
	def flush(self):
		self.console_file.flush()
		if self.log_file:
			self.log_file.flush()

# 로그 파일 설정
LOG_FILENAME = f'rt_search_log_{datetime.now(KST).strftime("%Y%m%d_%H%M%S")}.txt'
LOG_FILE = open(LOG_FILENAME, 'w', encoding='utf-8')

# stdout을 파일과 콘솔 모두에 출력하도록 설정
sys.stdout = TeeOutput(sys.stdout, LOG_FILE)

start_time_kst = datetime.now(KST)
print(f'로그 파일: {LOG_FILENAME}')
print(f'프로그램 시작 시간 (한국시간): {start_time_kst.strftime("%Y-%m-%d %H:%M:%S")}')
print(f'파일 저장 시간: 08:50 ~ 16:00 (한국시간)')
print('=' * 50)

SOCKET_URL = socket_url + '/api/dostk/websocket'  # 접속 URL
ACCESS_TOKEN = get_token()  # 고객 Access Token

# 종목코드로 종목명 조회 (동기 함수)
def get_stock_name(jmcode: str, token: str) -> str:
	"""종목코드로 종목명을 조회합니다. (키움 API 문서 참고: https://openapi.kiwoom.com/guide/apiguide)"""
	try:
		# 종목정보 조회 API 호출 (ka10099: 종목정보 리스트)
		endpoint = '/api/dostk/stkinfo'
		url = host_url + endpoint
		
		headers = {
			'Content-Type': 'application/json;charset=UTF-8',
			'authorization': f'Bearer {token}',
			'api-id': 'ka10099',
		}
		
		# 종목코드에서 'A' 접두사 제거 (예: A000660 -> 000660)
		clean_jmcode = jmcode.lstrip('A') if jmcode.startswith('A') else jmcode
		
		# 키움 API 문서에 따른 요청 데이터 구조
		data = {
			'jmcode': clean_jmcode
		}
		
		response = requests.post(url, headers=headers, json=data, timeout=5)
		
		if response.status_code == 200:
			result = response.json()
			
			# 응답 구조 확인: list 필드가 있는 경우
			if 'list' in result and isinstance(result['list'], list) and len(result['list']) > 0:
				stock_info = result['list'][0]
				jmname = (
					stock_info.get('jmname') or
					stock_info.get('stock_name') or
					stock_info.get('name') or
					stock_info.get('hname') or
					stock_info.get('stockName')
				)
				if jmname:
					return jmname
			
			# 응답 구조가 다른 경우
			if 'data' in result:
				data_info = result['data']
				if isinstance(data_info, dict):
					jmname = (
						data_info.get('jmname') or
						data_info.get('stock_name') or
						data_info.get('name') or
						data_info.get('hname')
					)
					if jmname:
						return jmname
				elif isinstance(data_info, list) and len(data_info) > 0:
					stock_info = data_info[0]
					jmname = (
						stock_info.get('jmname') or
						stock_info.get('stock_name') or
						stock_info.get('name') or
						stock_info.get('hname')
					)
					if jmname:
						return jmname
	except Exception as e:
		pass
	
	return '종목명없음'

class WebSocketClient:
	def __init__(self, uri):
		self.uri = uri
		self.websocket = None
		self.connected = False
		self.keep_running = True
		self.condition_name = None  # 선택한 조건검색명 저장

	# WebSocket 서버에 연결합니다.
	async def connect(self):
		try:
			self.websocket = await websockets.connect(self.uri)
			self.connected = True
			print("서버와 연결을 시도 중입니다.")

			# 로그인 패킷
			param = {
				'trnm': 'LOGIN',
				'token': ACCESS_TOKEN
			}

			print('실시간 시세 서버로 로그인 패킷을 전송합니다.')
			# 웹소켓 연결 시 로그인 정보 전달
			await self.send_message(message=param)

		except Exception as e:
			print(f'Connection error: {e}')
			self.connected = False

	# 서버에 메시지를 보냅니다. 연결이 없다면 자동으로 연결합니다.
	async def send_message(self, message):
		if not self.connected:
			await self.connect()  # 연결이 끊어졌다면 재연결
		
		# 메시지가 딕셔너리인지 확인 (PING 체크용)
		message_dict = message if isinstance(message, dict) else None
		if message_dict is None and isinstance(message, str):
			try:
				message_dict = json.loads(message)
			except:
				pass
		
		if self.connected:
			# message가 문자열이 아니면 JSON으로 직렬화
			if not isinstance(message, str):
				message_str = json.dumps(message)
			else:
				message_str = message

			await self.websocket.send(message_str)
			
			# PING 메시지인 경우 시간 정보 추가
			if message_dict and message_dict.get('trnm') == 'PING':
				current_time = datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')
				print(f'Message sent: {message_str} [시간: {current_time}]')
			else:
				print(f'Message sent: {message_str}')

	# 서버에서 오는 메시지를 수신하여 출력합니다.
	async def receive_messages(self):
		while self.keep_running:
			try:
				# 서버로부터 수신한 메시지를 JSON 형식으로 파싱
				response = json.loads(await self.websocket.recv())

				# 메시지 유형이 LOGIN일 경우 로그인 시도 결과 체크
				if response.get('trnm') == 'LOGIN':
					if response.get('return_code') != 0:
						print('로그인 실패하였습니다. : ', response.get('return_msg'))
						await self.disconnect()
					else:
						print('로그인 성공하였습니다.')
						# 조건검색 목록조회 패킷 전송 (서버 초기화용, 응답은 출력하지 않음)
						param = {
							'trnm': 'CNSRLST'
						}
						await self.send_message(message=param)

				# 메시지 유형이 PING일 경우 수신값 그대로 송신
				elif response.get('trnm') == 'PING':
					await self.send_message(response)

				# CNSRLST 응답에서 조건검색명 추출
				if response.get('trnm') == 'CNSRLST':
					data = response.get('data')
					if isinstance(data, list):
						# target_seq가 설정되어 있으면 해당 조건검색명 찾기
						target_seq = getattr(self, 'target_seq', None)
						if target_seq is not None:
							for item in data:
								# 응답 구조: [[seq, condition_name], ...]
								if isinstance(item, list) and len(item) >= 2:
									item_seq = str(item[0])  # 첫 번째 요소가 seq
									if item_seq == str(target_seq):
										self.condition_name = str(item[1])  # 두 번째 요소가 조건검색명
										if self.condition_name:
											print(f'조건검색명: {self.condition_name} (seq: {item_seq})')
											break

				# CNSRREQ 응답 처리 (보기 좋게 정렬하여 출력)
				if response.get('trnm') == 'CNSRREQ':
					return_code = response.get('return_code', -1)
					seq = response.get('seq', 'N/A')
					data = response.get('data', [])
					
					condition_info = f'[{self.condition_name}] ' if self.condition_name else ''
					
					print(f'\n{condition_info}조건검색 결과 (seq: {seq}, return_code: {return_code})')
					print('=' * 80)
					
					if isinstance(data, list) and len(data) > 0:
						print(f'총 {len(data)}건의 종목이 검색되었습니다.')
						print('-' * 80)
						print(f'{"번호":<6s} {"종목코드":<12s} {"종목명":<30s}')
						print('-' * 80)
						
						# 종목코드와 종목명을 페어로 출력
						for idx, item in enumerate(data, 1):
							if isinstance(item, dict):
								jmcode = item.get('jmcode', 'N/A')
							elif isinstance(item, str):
								jmcode = item
							else:
								jmcode = str(item)
							
							# 종목명 조회 (비동기 환경에서 동기 함수 호출)
							jmname = await asyncio.to_thread(get_stock_name, jmcode, ACCESS_TOKEN)
							
							print(f'{idx:<6d} {jmcode:<12s} {jmname:<30s}')
						
						print('-' * 80)
					else:
						print('조건검색 결과가 없습니다.')
						print('-' * 80)

				# CNSRLST 응답은 출력하지 않음 (서버 초기화용으로만 사용)
				if response.get('trnm') != 'PING' and response.get('trnm') != 'CNSRLST' and response.get('trnm') != 'CNSRREQ':
					print(f'실시간 시세 서버 응답 수신: {response}')

					if response.get('trnm') == 'REAL' and response.get('data'):
						items = response['data']
						for item in items:
							jmcode = item['values']['9001']
							print(f"종목코드: {jmcode}")

			except websockets.ConnectionClosed:
				print('Connection closed by the server')
				self.connected = False
				await self.websocket.close()

	# WebSocket 실행
	async def run(self):
		await self.connect()
		await self.receive_messages()

	# WebSocket 연결 종료
	async def disconnect(self):
		self.keep_running = False
		if self.connected and self.websocket:
			await self.websocket.close()
			self.connected = False
			print('Disconnected from WebSocket server')

async def main():
	# 조건검색식 일련번호 설정
	TARGET_SEQ = '0'
	
	print(f'조건검색식 일련번호: {TARGET_SEQ}')
	
	# WebSocketClient 전역 변수 선언
	websocket_client = WebSocketClient(SOCKET_URL)
	websocket_client.target_seq = TARGET_SEQ  # 조건검색 seq를 클라이언트에 전달

	# WebSocket 클라이언트를 백그라운드에서 실행합니다.
	receive_task = asyncio.create_task(websocket_client.run())

	# 조건검색명이 로드될 때까지 대기
	await asyncio.sleep(2)
	
	# 조건검색명이 아직 로드되지 않았다면 출력
	if not websocket_client.condition_name:
		print(f'조건검색명을 로드하는 중... (seq: {TARGET_SEQ})')
	
	# 실시간 항목 등록
	await websocket_client.send_message({ 
		'trnm': 'CNSRREQ', # 서비스명
		'seq': TARGET_SEQ, # 조건검색식 일련번호
		'search_type': '1', # 조회타입
		'stex_tp': 'K', # 거래소구분
	})

	# 수신 작업이 종료될 때까지 대기
	await receive_task

# asyncio로 프로그램을 실행합니다.
if __name__ == '__main__':
	try:
		asyncio.run(main())
	finally:
		# 프로그램 종료 시 로그 파일 닫기
		end_time_kst = datetime.now(KST)
		print(f'\n프로그램 종료 시간 (한국시간): {end_time_kst.strftime("%Y-%m-%d %H:%M:%S")}')
		print('=' * 50)
		if LOG_FILE:
			LOG_FILE.close()
			print(f'로그 파일 저장 완료: {LOG_FILENAME}')