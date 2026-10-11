import asyncio 
import websockets
import json
import requests
import sys
import aiosqlite
import sqlite3
from datetime import datetime, timedelta, timezone
from config import socket_url, host_url
from login import fn_au10001 as get_token
from rich.console import Console
from rich.table import Table

# 한국 시간대 설정 (UTC+9)
KST = timezone(timedelta(hours=9))

# Rich 콘솔 초기화
console = Console()

# 콘솔 출력을 파일로도 저장하는 클래스
class TeeOutput:
	"""콘솔과 파일에 동시에 출력하는 클래스"""
	def __init__(self, *files):
		self.files = files
	
	def write(self, obj):
		for f in self.files:
			f.write(obj)
			f.flush()  # 즉시 파일에 쓰기
	
	def flush(self):
		for f in self.files:
			f.flush()

# 로그 파일 설정
LOG_FILENAME = f'rt_search_log_{datetime.now(KST).strftime("%Y%m%d_%H%M%S")}.txt'
LOG_FILE = open(LOG_FILENAME, 'w', encoding='utf-8')

# stdout을 파일과 콘솔 모두에 출력하도록 설정
sys.stdout = TeeOutput(sys.stdout, LOG_FILE)

start_time_kst = datetime.now(KST)
print(f'로그 파일: {LOG_FILENAME}')
print(f'프로그램 시작 시간 (한국시간): {start_time_kst.strftime("%Y-%m-%d %H:%M:%S")}')
print('=' * 50)

SOCKET_URL = socket_url + '/api/dostk/websocket'  # 접속 URL
ACCESS_TOKEN = get_token()  # 고객 Access Token

# 데이터베이스 파일명
DB_FILE = 'stock_conditions.db'

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
		# 개별 종목 조회를 위해 jmcode 사용
		data = {
			'jmcode': clean_jmcode
		}
		
		response = requests.post(url, headers=headers, json=data, timeout=5)
		
		if response.status_code == 200:
			result = response.json()
			
			# 응답 구조 확인: list 필드가 있는 경우
			if 'list' in result and isinstance(result['list'], list) and len(result['list']) > 0:
				# list의 첫 번째 항목에서 종목명 추출
				stock_info = result['list'][0]
				# 가능한 종목명 필드명 확인
				jmname = (
					stock_info.get('jmname') or
					stock_info.get('stock_name') or
					stock_info.get('name') or
					stock_info.get('hname') or
					stock_info.get('stockName')
				)
				if jmname:
					return jmname
			
			# 응답 구조가 다른 경우 (직접 data 필드에 있는 경우)
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
		else:
			# API 오류 응답 확인
			try:
				error_result = response.json()
				print(f'[종목명 조회 오류] {jmcode}: {error_result.get("return_msg", "알 수 없는 오류")}')
			except:
				pass
				
	except requests.exceptions.Timeout:
		pass  # 타임아웃은 조용히 처리
	except Exception as e:
		# 디버깅용 (필요시 주석 해제)
		# print(f'[종목명 조회 예외] {jmcode}: {str(e)}')
		pass
	
	return '종목명없음'

# 숫자 포맷팅 함수들
def format_number(value):
	"""숫자 문자열을 천 단위 구분자로 포맷팅"""
	if value == 'N/A' or not value:
		return 'N/A'
	try:
		num = int(value)
		return f'{num:,}'
	except:
		return value

def format_price(value):
	"""가격 문자열을 천 단위 구분자로 포맷팅"""
	if value == 'N/A' or not value:
		return 'N/A'
	try:
		num = int(value)
		return f'{num:,}'
	except:
		return value

def format_rate(value):
	"""등락율 포맷팅 (값을 1000으로 나눠서 퍼센트로 표시)"""
	if value == 'N/A' or not value:
		return 'N/A'
	try:
		num = float(value)
		# 등락율은 1000분율로 들어오므로 1000으로 나눔 (예: 270 -> 0.27%)
		percent = num / 1000.0
		return f'{percent:.2f}%'
	except:
		return value

def get_change_symbol(symbol_code):
	"""전일대비기호 변환 (2:상한, 3:상승, 4:보합, 5:하락, 6:하한)"""
	symbol_map = {
		'2': '▲',  # 상한
		'3': '▲',  # 상승
		'4': '－',  # 보합
		'5': '▼',  # 하락
		'6': '▼'   # 하한
	}
	return symbol_map.get(str(symbol_code), '')

def calculate_trading_amount(current_price, volume):
	"""거래대금 계산 (현재가 × 누적거래량)"""
	if current_price == 'N/A' or volume == 'N/A' or not current_price or not volume:
		return 'N/A'
	try:
		price = int(current_price)
		vol = int(volume)
		amount = price * vol
		return f'{amount:,}'
	except:
		return 'N/A'

# ==================== SQLite 데이터베이스 함수 ====================

async def init_database():
	"""데이터베이스 초기화"""
	async with aiosqlite.connect(DB_FILE) as db:
		cursor = await db.cursor()
		
		# 테이블 생성
		await cursor.execute('''
			CREATE TABLE IF NOT EXISTS stock_conditions (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				condition_name TEXT NOT NULL,
				seq TEXT NOT NULL,
				jmcode TEXT NOT NULL,
				jmname TEXT,
				current_price INTEGER,
				change_price INTEGER,
				change_rate REAL,
				volume INTEGER,
				trading_amount INTEGER,
				low_price INTEGER,
				created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
				UNIQUE(condition_name, jmcode, created_at)
			)
		''')
		
		# 인덱스 생성 (조회 성능 향상)
		await cursor.execute('CREATE INDEX IF NOT EXISTS idx_jmcode ON stock_conditions(jmcode)')
		await cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON stock_conditions(created_at)')
		await cursor.execute('CREATE INDEX IF NOT EXISTS idx_condition_name ON stock_conditions(condition_name)')
		
		await db.commit()
		print(f'[SQLite] 데이터베이스 초기화 완료: {DB_FILE}')

async def save_stock_data(condition_name, seq, jmcode, jmname=None, current_price=None,
						  change_price=None, change_rate=None, volume=None,
						  trading_amount=None, low_price=None):
	"""주식 데이터를 데이터베이스에 저장 (비동기)"""
	try:
		async with aiosqlite.connect(DB_FILE) as db:
			cursor = await db.cursor()
			
			# 등락율을 숫자로 변환 (1000분율 -> 소수)
			change_rate_value = None
			if change_rate and change_rate != 'N/A':
				try:
					# format_rate에서 반환된 문자열에서 % 제거하고 숫자로 변환
					if isinstance(change_rate, str) and '%' in change_rate:
						change_rate_value = float(change_rate.replace('%', ''))
					else:
						change_rate_value = float(change_rate) / 1000.0  # 1000분율을 소수로 변환
				except:
					change_rate_value = None
			
			# 숫자 값 변환
			current_price_int = None
			if current_price and current_price != 'N/A':
				try:
					current_price_int = int(str(current_price).replace(',', ''))
				except:
					pass
			
			change_price_int = None
			if change_price and change_price != 'N/A':
				try:
					change_price_int = int(str(change_price).replace(',', ''))
				except:
					pass
			
			volume_int = None
			if volume and volume != 'N/A':
				try:
					volume_int = int(str(volume).replace(',', ''))
				except:
					pass
			
			trading_amount_int = None
			if trading_amount and trading_amount != 'N/A':
				try:
					trading_amount_int = int(str(trading_amount).replace(',', ''))
				except:
					pass
			
			low_price_int = None
			if low_price and low_price != 'N/A':
				try:
					low_price_int = int(str(low_price).replace(',', ''))
				except:
					pass
			
			await cursor.execute('''
				INSERT OR IGNORE INTO stock_conditions 
				(condition_name, seq, jmcode, jmname, current_price, change_price, 
				 change_rate, volume, trading_amount, low_price, created_at)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
			''', (condition_name, seq, jmcode, jmname, current_price_int, change_price_int,
				  change_rate_value, volume_int, trading_amount_int, low_price_int, datetime.now(KST)))
			
			await db.commit()
	except sqlite3.IntegrityError:
		# 중복 데이터는 무시 (UNIQUE 제약조건)
		pass
	except Exception as e:
		# 데이터베이스 저장 오류는 조용히 처리 (메인 로직에 영향 없도록)
		pass

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
		if self.connected:
			# message가 문자열이 아니면 JSON으로 직렬화
			if not isinstance(message, str):
				message = json.dumps(message)

		await self.websocket.send(message)
		print(f'Message sent: {message}')

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
						print('조건검색 목록조회 패킷을 전송합니다.')
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
					seq = response.get('seq', 'N/A').strip()  # 공백 제거
					cont_yn = response.get('cont_yn', 'N')
					next_key = response.get('next_key', '')
					data = response.get('data', [])
					
					if return_code != 0:
						print(f'[CNSRREQ 오류] return_code: {return_code}, return_msg: {response.get("return_msg", "알 수 없음")}')
						continue  # 오류 발생 시 다음 메시지 처리
					
					condition_info = f'[{self.condition_name}] ' if self.condition_name else ''
					
					print(f'\n{condition_info}조건검색 결과 (seq: {seq}, return_code: {return_code})')
					if cont_yn == 'Y':
						print(f'연속조회 가능 (next_key: {next_key})')
					print('=' * 132)
					
					if isinstance(data, list) and len(data) > 0:
						# 거래대금 기준으로 정렬 (내림차순)
						def get_trading_amount_value(item):
							"""정렬을 위한 거래대금 값 추출"""
							if isinstance(item, dict):
								cur_price_raw = item.get('10', '0')
								volume_raw = item.get('13', '0')
								try:
									price = int(cur_price_raw) if cur_price_raw != 'N/A' else 0
									vol = int(volume_raw) if volume_raw != 'N/A' else 0
									return price * vol
								except:
									return 0
							return 0
						
						# 거래대금 순으로 정렬 (내림차순)
						sorted_data = sorted(data, key=get_trading_amount_value, reverse=True)
						
						# Rich 테이블 생성
						table = Table(
							title=f'{condition_info}조건검색 결과 (seq: {seq}, return_code: {return_code}) - 총 {len(sorted_data)}건 (거래대금 순)',
							show_header=True,
							header_style="bold magenta"
						)
						
						# 컬럼 추가
						table.add_column("번호", justify="center", style="cyan", width=6)
						table.add_column("종목코드", justify="left", style="yellow", width=12)
						table.add_column("종목명", justify="left", style="white", width=22)
						table.add_column("현재가", justify="right", style="green", width=14)
						table.add_column("대비", justify="center", style="white", width=4)
						table.add_column("전일대비", justify="right", style="white", width=14)
						table.add_column("등락율", justify="right", style="white", width=10)
						table.add_column("거래량", justify="right", style="blue", width=16)
						table.add_column("거래대금", justify="right", style="bold yellow", width=20)
						table.add_column("저가", justify="right", style="white", width=14)
						
						# 데이터 행 추가 및 데이터베이스 저장
						for idx, item in enumerate(sorted_data, 1):
							if isinstance(item, dict):
								# API 문서에 따른 필드 추출
								jmcode = item.get('9001', 'N/A')      # 종목코드
								jmname = item.get('302', 'N/A')       # 종목명
								cur_price_raw = item.get('10', 'N/A')  # 현재가 (원본)
								cur_price = format_price(cur_price_raw)  # 현재가 (포맷팅)
								change_symbol_code = item.get('25', '')  # 전일대비기호
								change_symbol = get_change_symbol(change_symbol_code)
								change = format_price(item.get('11', 'N/A'))  # 전일대비
								change_rate_raw = item.get('12', 'N/A')  # 등락율 (원본)
								change_rate = format_rate(change_rate_raw)  # 등락율 (포맷팅)
								volume_raw = item.get('13', 'N/A')  # 누적거래량 (원본)
								volume = format_number(volume_raw)  # 누적거래량 (포맷팅)
								trading_amount = calculate_trading_amount(cur_price_raw, volume_raw)  # 거래대금 계산
								low_price = format_price(item.get('18', 'N/A'))  # 저가
								
								# 등락율에 따른 색상 설정
								change_rate_style = "green" if change_symbol_code in ['2', '3'] else "red" if change_symbol_code in ['5', '6'] else "white"
								
								table.add_row(
									str(idx),
									jmcode,
									jmname,
									cur_price,
									change_symbol,
									change,
									f'[{change_rate_style}]{change_rate}[/{change_rate_style}]',
									volume,
									trading_amount,
									low_price
								)
								
								# 데이터베이스에 저장 (백그라운드 태스크로 실행)
								if jmcode != 'N/A' and self.condition_name:
									# 거래대금 계산 (현재가 × 거래량)
									trading_amount_value = None
									if cur_price_raw != 'N/A' and volume_raw != 'N/A':
										try:
											price = int(cur_price_raw)
											vol = int(volume_raw)
											trading_amount_value = price * vol
										except:
											pass
									
									asyncio.create_task(save_stock_data(
										condition_name=self.condition_name,
										seq=seq,
										jmcode=jmcode,
										jmname=jmname if jmname != 'N/A' else None,
										current_price=cur_price_raw,
										change_price=item.get('11', 'N/A'),
										change_rate=change_rate_raw,
										volume=volume_raw,
										trading_amount=trading_amount_value,
										low_price=item.get('18', 'N/A')
									))
							elif isinstance(item, str):
								table.add_row(str(idx), item, "N/A", "N/A", "", "N/A", "N/A", "N/A", "N/A", "N/A")
							else:
								table.add_row(str(idx), str(item), "N/A", "N/A", "", "N/A", "N/A", "N/A", "N/A", "N/A")
						
						# 테이블 출력
						console.print()
						console.print(table)
					else:
						print('조건검색 결과가 없습니다.')
						print('-' * 132)

				# 조건검색 결과 처리 (REAL 메시지)
				if response.get('trnm') == 'REAL' and response.get('data'):
					items = response['data']
					condition_info = f'[{self.condition_name}] ' if self.condition_name else ''
					
					if isinstance(items, list) and len(items) > 0:
						# 거래대금 기준으로 정렬 (내림차순)
						def get_trading_amount_value(item):
							"""정렬을 위한 거래대금 값 추출"""
							if isinstance(item, dict):
								values = item.get('values', {})
								cur_price_raw = values.get('10', '0')
								volume_raw = values.get('13', '0')
								try:
									price = int(cur_price_raw) if cur_price_raw != 'N/A' else 0
									vol = int(volume_raw) if volume_raw != 'N/A' else 0
									return price * vol
								except:
									return 0
							return 0
						
						# 거래대금 순으로 정렬 (내림차순)
						sorted_items = sorted(items, key=get_trading_amount_value, reverse=True)
						
						# Rich 테이블 생성
						table = Table(
							title=f'{condition_info}실시간 조건검색 결과 - 총 {len(sorted_items)}건 (거래대금 순)',
							show_header=True,
							header_style="bold magenta"
						)
						
						# 컬럼 추가
						table.add_column("번호", justify="center", style="cyan", width=6)
						table.add_column("종목코드", justify="left", style="yellow", width=12)
						table.add_column("종목명", justify="left", style="white", width=22)
						table.add_column("현재가", justify="right", style="green", width=14)
						table.add_column("대비", justify="center", style="white", width=4)
						table.add_column("전일대비", justify="right", style="white", width=14)
						table.add_column("등락율", justify="right", style="white", width=10)
						table.add_column("거래량", justify="right", style="blue", width=16)
						table.add_column("거래대금", justify="right", style="bold yellow", width=20)
						table.add_column("저가", justify="right", style="white", width=14)
						
						# 데이터 행 추가 및 데이터베이스 저장
						for idx, item in enumerate(sorted_items, 1):
							if isinstance(item, dict):
								values = item.get('values', {})
								# API 문서에 따른 필드 추출
								jmcode = values.get('9001', 'N/A')      # 종목코드
								jmname = values.get('302', '') or values.get('3021', '') or values.get('9002', '') or '종목명없음'  # 종목명
								cur_price_raw = values.get('10', 'N/A')  # 현재가 (원본)
								cur_price = format_price(cur_price_raw)  # 현재가 (포맷팅)
								change_symbol_code = values.get('25', '')  # 전일대비기호
								change_symbol = get_change_symbol(change_symbol_code)
								change = format_price(values.get('11', 'N/A'))  # 전일대비
								change_rate_raw = values.get('12', 'N/A')  # 등락율 (원본)
								change_rate = format_rate(change_rate_raw)  # 등락율 (포맷팅)
								volume_raw = values.get('13', 'N/A')  # 누적거래량 (원본)
								volume = format_number(volume_raw)  # 누적거래량 (포맷팅)
								trading_amount = calculate_trading_amount(cur_price_raw, volume_raw)  # 거래대금 계산
								low_price = format_price(values.get('18', 'N/A'))  # 저가
								
								# 등락율에 따른 색상 설정
								change_rate_style = "green" if change_symbol_code in ['2', '3'] else "red" if change_symbol_code in ['5', '6'] else "white"
								
								table.add_row(
									str(idx),
									jmcode,
									jmname,
									cur_price,
									change_symbol,
									change,
									f'[{change_rate_style}]{change_rate}[/{change_rate_style}]',
									volume,
									trading_amount,
									low_price
								)
								
								# 데이터베이스에 저장 (백그라운드 태스크로 실행)
								if jmcode != 'N/A' and self.condition_name:
									# seq는 target_seq에서 가져오기
									target_seq = getattr(self, 'target_seq', '0')
									
									# 거래대금 계산 (현재가 × 거래량)
									trading_amount_value = None
									if cur_price_raw != 'N/A' and volume_raw != 'N/A':
										try:
											price = int(cur_price_raw)
											vol = int(volume_raw)
											trading_amount_value = price * vol
										except:
											pass
									
									asyncio.create_task(save_stock_data(
										condition_name=self.condition_name,
										seq=target_seq,
										jmcode=jmcode,
										jmname=jmname if jmname != '종목명없음' else None,
										current_price=cur_price_raw,
										change_price=values.get('11', 'N/A'),
										change_rate=change_rate_raw,
										volume=volume_raw,
										trading_amount=trading_amount_value,
										low_price=values.get('18', 'N/A')
									))
						
						# 테이블 출력
						console.print()
						console.print(table)
					else:
						print(f'\n{condition_info}실시간 조건검색 결과가 없습니다.')

				# CNSRLST, CNSRREQ, REAL 응답은 출력하지 않음 (서버 초기화용으로만 사용)
				# 다만 디버깅이 필요하면 임시로 출력 가능
				if response.get('trnm') != 'PING' and response.get('trnm') != 'CNSRLST' and response.get('trnm') != 'CNSRREQ' and response.get('trnm') != 'REAL':
					print(f'실시간 시세 서버 응답 수신: {response}')

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
	
	# 데이터베이스 초기화
	await init_database()
	
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
		'stex_tp': 'K' # 거래소구분
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
