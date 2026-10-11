"""
SQLite 사용 예제 코드
- 동기 방식 (sqlite3)
- 비동기 방식 (aiosqlite)
"""

import sqlite3
import aiosqlite
import asyncio
from datetime import datetime, timedelta, timezone

# 한국 시간대 설정 (UTC+9)
KST = timezone(timedelta(hours=9))

# 데이터베이스 파일명
DB_FILE = 'stock_data.db'

# ==================== 동기 방식 (sqlite3) ====================

def init_database_sync():
	"""데이터베이스 초기화 (동기 방식)"""
	conn = sqlite3.connect(DB_FILE)
	cursor = conn.cursor()
	
	# 테이블 생성
	cursor.execute('''
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
	cursor.execute('CREATE INDEX IF NOT EXISTS idx_jmcode ON stock_conditions(jmcode)')
	cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON stock_conditions(created_at)')
	cursor.execute('CREATE INDEX IF NOT EXISTS idx_condition_name ON stock_conditions(condition_name)')
	
	conn.commit()
	conn.close()
	print(f'[동기] 데이터베이스 초기화 완료: {DB_FILE}')

def insert_stock_data_sync(condition_name, seq, jmcode, jmname=None, current_price=None, 
						   change_price=None, change_rate=None, volume=None, 
						   trading_amount=None, low_price=None):
	"""주식 데이터 삽입 (동기 방식)"""
	conn = sqlite3.connect(DB_FILE)
	cursor = conn.cursor()
	
	try:
		cursor.execute('''
			INSERT INTO stock_conditions 
			(condition_name, seq, jmcode, jmname, current_price, change_price, 
			 change_rate, volume, trading_amount, low_price, created_at)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
		''', (condition_name, seq, jmcode, jmname, current_price, change_price,
			  change_rate, volume, trading_amount, low_price, datetime.now(KST)))
		
		conn.commit()
		print(f'[동기] 데이터 삽입 완료: {jmcode} ({jmname})')
		return True
	except sqlite3.IntegrityError:
		print(f'[동기] 중복 데이터 무시: {jmcode}')
		return False
	except Exception as e:
		print(f'[동기] 데이터 삽입 오류: {e}')
		return False
	finally:
		conn.close()

def query_stock_data_sync(condition_name=None, jmcode=None, limit=10):
	"""주식 데이터 조회 (동기 방식)"""
	conn = sqlite3.connect(DB_FILE)
	cursor = conn.cursor()
	
	try:
		query = 'SELECT * FROM stock_conditions WHERE 1=1'
		params = []
		
		if condition_name:
			query += ' AND condition_name = ?'
			params.append(condition_name)
		
		if jmcode:
			query += ' AND jmcode = ?'
			params.append(jmcode)
		
		query += ' ORDER BY created_at DESC LIMIT ?'
		params.append(limit)
		
		cursor.execute(query, params)
		results = cursor.fetchall()
		
		print(f'\n[동기] 조회 결과 ({len(results)}건):')
		print('-' * 100)
		print(f'{"ID":<5} {"조건명":<20} {"종목코드":<12} {"종목명":<15} {"현재가":<12} {"거래대금":<15} {"생성시간":<20}')
		print('-' * 100)
		
		for row in results:
			(row_id, cond_name, seq, code, name, cur_price, chg_price, 
			 chg_rate, vol, trading_amt, low_pr, created_at) = row
			
			cur_price_str = f'{cur_price:,}' if cur_price else 'N/A'
			trading_amt_str = f'{trading_amt:,}' if trading_amt else 'N/A'
			
			print(f'{row_id:<5} {cond_name:<20} {code:<12} {name or "N/A":<15} '
				  f'{cur_price_str:<12} {trading_amt_str:<15} {created_at:<20}')
		
		print('-' * 100)
		return results
	except Exception as e:
		print(f'[동기] 조회 오류: {e}')
		return []
	finally:
		conn.close()

def get_statistics_sync():
	"""통계 정보 조회 (동기 방식)"""
	conn = sqlite3.connect(DB_FILE)
	cursor = conn.cursor()
	
	try:
		# 전체 레코드 수
		cursor.execute('SELECT COUNT(*) FROM stock_conditions')
		total_count = cursor.fetchone()[0]
		
		# 조건별 그룹
		cursor.execute('''
			SELECT condition_name, COUNT(*) as cnt 
			FROM stock_conditions 
			GROUP BY condition_name
		''')
		condition_counts = cursor.fetchall()
		
		# 최근 데이터 시간
		cursor.execute('SELECT MAX(created_at) FROM stock_conditions')
		latest_time = cursor.fetchone()[0]
		
		print('\n[동기] 통계 정보:')
		print('-' * 50)
		print(f'전체 레코드 수: {total_count:,}건')
		print(f'최근 데이터 시간: {latest_time or "N/A"}')
		print('\n조건별 데이터 수:')
		for cond_name, cnt in condition_counts:
			print(f'  - {cond_name}: {cnt:,}건')
		print('-' * 50)
		
		return {
			'total_count': total_count,
			'condition_counts': condition_counts,
			'latest_time': latest_time
		}
	except Exception as e:
		print(f'[동기] 통계 조회 오류: {e}')
		return None
	finally:
		conn.close()

# ==================== 비동기 방식 (aiosqlite) ====================

async def init_database_async():
	"""데이터베이스 초기화 (비동기 방식)"""
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
		
		# 인덱스 생성
		await cursor.execute('CREATE INDEX IF NOT EXISTS idx_jmcode ON stock_conditions(jmcode)')
		await cursor.execute('CREATE INDEX IF NOT EXISTS idx_created_at ON stock_conditions(created_at)')
		await cursor.execute('CREATE INDEX IF NOT EXISTS idx_condition_name ON stock_conditions(condition_name)')
		
		await db.commit()
		print(f'[비동기] 데이터베이스 초기화 완료: {DB_FILE}')

async def insert_stock_data_async(condition_name, seq, jmcode, jmname=None, current_price=None,
								  change_price=None, change_rate=None, volume=None,
								  trading_amount=None, low_price=None):
	"""주식 데이터 삽입 (비동기 방식)"""
	async with aiosqlite.connect(DB_FILE) as db:
		cursor = await db.cursor()
		
		try:
			await cursor.execute('''
				INSERT INTO stock_conditions 
				(condition_name, seq, jmcode, jmname, current_price, change_price, 
				 change_rate, volume, trading_amount, low_price, created_at)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
			''', (condition_name, seq, jmcode, jmname, current_price, change_price,
				  change_rate, volume, trading_amount, low_price, datetime.now(KST)))
			
			await db.commit()
			print(f'[비동기] 데이터 삽입 완료: {jmcode} ({jmname})')
			return True
		except sqlite3.IntegrityError:
			print(f'[비동기] 중복 데이터 무시: {jmcode}')
			return False
		except Exception as e:
			print(f'[비동기] 데이터 삽입 오류: {e}')
			return False

async def query_stock_data_async(condition_name=None, jmcode=None, limit=10):
	"""주식 데이터 조회 (비동기 방식)"""
	async with aiosqlite.connect(DB_FILE) as db:
		cursor = await db.cursor()
		
		try:
			query = 'SELECT * FROM stock_conditions WHERE 1=1'
			params = []
			
			if condition_name:
				query += ' AND condition_name = ?'
				params.append(condition_name)
			
			if jmcode:
				query += ' AND jmcode = ?'
				params.append(jmcode)
			
			query += ' ORDER BY created_at DESC LIMIT ?'
			params.append(limit)
			
			await cursor.execute(query, params)
			results = await cursor.fetchall()
			
			print(f'\n[비동기] 조회 결과 ({len(results)}건):')
			print('-' * 100)
			print(f'{"ID":<5} {"조건명":<20} {"종목코드":<12} {"종목명":<15} {"현재가":<12} {"거래대금":<15} {"생성시간":<20}')
			print('-' * 100)
			
			for row in results:
				(row_id, cond_name, seq, code, name, cur_price, chg_price,
				 chg_rate, vol, trading_amt, low_pr, created_at) = row
				
				cur_price_str = f'{cur_price:,}' if cur_price else 'N/A'
				trading_amt_str = f'{trading_amt:,}' if trading_amt else 'N/A'
				
				print(f'{row_id:<5} {cond_name:<20} {code:<12} {name or "N/A":<15} '
					  f'{cur_price_str:<12} {trading_amt_str:<15} {created_at:<20}')
			
			print('-' * 100)
			return results
		except Exception as e:
			print(f'[비동기] 조회 오류: {e}')
			return []

async def get_statistics_async():
	"""통계 정보 조회 (비동기 방식)"""
	async with aiosqlite.connect(DB_FILE) as db:
		cursor = await db.cursor()
		
		try:
			# 전체 레코드 수
			await cursor.execute('SELECT COUNT(*) FROM stock_conditions')
			total_count = (await cursor.fetchone())[0]
			
			# 조건별 그룹
			await cursor.execute('''
				SELECT condition_name, COUNT(*) as cnt 
				FROM stock_conditions 
				GROUP BY condition_name
			''')
			condition_counts = await cursor.fetchall()
			
			# 최근 데이터 시간
			await cursor.execute('SELECT MAX(created_at) FROM stock_conditions')
			latest_time = (await cursor.fetchone())[0]
			
			print('\n[비동기] 통계 정보:')
			print('-' * 50)
			print(f'전체 레코드 수: {total_count:,}건')
			print(f'최근 데이터 시간: {latest_time or "N/A"}')
			print('\n조건별 데이터 수:')
			for cond_name, cnt in condition_counts:
				print(f'  - {cond_name}: {cnt:,}건')
			print('-' * 50)
			
			return {
				'total_count': total_count,
				'condition_counts': condition_counts,
				'latest_time': latest_time
			}
		except Exception as e:
			print(f'[비동기] 통계 조회 오류: {e}')
			return None

# ==================== 예제 실행 ====================

def example_sync():
	"""동기 방식 예제"""
	print('\n' + '=' * 50)
	print('동기 방식 (sqlite3) 예제')
	print('=' * 50)
	
	# 데이터베이스 초기화
	init_database_sync()
	
	# 샘플 데이터 삽입
	insert_stock_data_sync(
		condition_name='테스트 조건',
		seq='0',
		jmcode='005930',
		jmname='삼성전자',
		current_price=75000,
		change_price=1000,
		change_rate=1.35,
		volume=1000000,
		trading_amount=75000000000,
		low_price=74000
	)
	
	insert_stock_data_sync(
		condition_name='테스트 조건',
		seq='0',
		jmcode='000660',
		jmname='SK하이닉스',
		current_price=150000,
		change_price=-2000,
		change_rate=-1.32,
		volume=500000,
		trading_amount=75000000000,
		low_price=148000
	)
	
	# 데이터 조회
	query_stock_data_sync(condition_name='테스트 조건', limit=5)
	
	# 통계 정보
	get_statistics_sync()

async def example_async():
	"""비동기 방식 예제"""
	print('\n' + '=' * 50)
	print('비동기 방식 (aiosqlite) 예제')
	print('=' * 50)
	
	# 데이터베이스 초기화
	await init_database_async()
	
	# 샘플 데이터 삽입
	await insert_stock_data_async(
		condition_name='비동기 테스트',
		seq='1',
		jmcode='035420',
		jmname='NAVER',
		current_price=200000,
		change_price=5000,
		change_rate=2.56,
		volume=200000,
		trading_amount=40000000000,
		low_price=195000
	)
	
	await insert_stock_data_async(
		condition_name='비동기 테스트',
		seq='1',
		jmcode='035720',
		jmname='카카오',
		current_price=50000,
		change_price=-1000,
		change_rate=-1.96,
		volume=300000,
		trading_amount=15000000000,
		low_price=49000
	)
	
	# 데이터 조회
	await query_stock_data_async(condition_name='비동기 테스트', limit=5)
	
	# 통계 정보
	await get_statistics_async()

async def main():
	"""메인 함수"""
	# 동기 방식 예제 실행
	example_sync()
	
	# 비동기 방식 예제 실행
	await example_async()
	
	print('\n' + '=' * 50)
	print('예제 실행 완료!')
	print('=' * 50)

if __name__ == '__main__':
	asyncio.run(main())
