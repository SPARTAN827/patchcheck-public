"""Acquire original Mendeley ZIP members by range; no relevance selection."""
import argparse, concurrent.futures, datetime as dt, hashlib, json, struct
import threading, time, urllib.request, urllib.error, zlib
from pathlib import Path

BASE = Path(__file__).resolve().parent
URL = 'https://prod-dcd-datasets-public-files-eu-west-1.s3.eu-west-1.amazonaws.com/09790ce2-3c84-4983-8de4-8dded94044ba'
stop = threading.Event()

def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def dump(path, obj):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)

def fetch(row):
    aid = str(row['appid'])
    rec = dict(row, started_at_utc=now(), archive_url=URL)
    dest = BASE / 'raw' / Path(row['name']).name
    receipt = BASE / 'acquisition' / (aid + '.json')
    if dest.exists():
        data = dest.read_bytes()
        assert len(data) == row['size'] and zlib.crc32(data) == row['crc']
        rec.update(status='verified_existing', path=str(dest), sha256=hashlib.sha256(data).hexdigest(), ended_at_utc=now())
        dump(receipt, rec)
        return rec
    if stop.is_set():
        rec.update(status='not_requested_after_stop', ended_at_utc=now()); dump(receipt,rec); return rec
    try:
        assert row['size'] <= 50_000_000 and row['compressed_size'] <= 50_000_000
        offset = row['offset']; end = offset + row['compressed_size'] + 4095
        request = urllib.request.Request(URL, headers={'Range':f'bytes={offset}-{end}', 'User-Agent':'PatchCheck academic research; public dataset range extraction'})
        with urllib.request.urlopen(request, timeout=45) as response:
            rec.update(http_status=response.status, content_range=response.headers.get('Content-Range'), final_url=response.geturl())
            if response.status != 206: raise ValueError('Expected partial range response')
            if not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):
                raise ValueError('Range start mismatch')
            raw = response.read(row['compressed_size'] + 4097)
        header = struct.unpack('<4s5H3I2H',raw[:30])
        assert header[0] == b'PK\x03\x04' and header[3] == 8
        start = 30 + header[-2] + header[-1]
        payload = raw[start:start + row['compressed_size']]
        assert len(payload) == row['compressed_size']
        data = zlib.decompress(payload,-15)
        assert len(data) == row['size'] and zlib.crc32(data) == row['crc']
        dest.write_bytes(data)
        rec.update(status='acquired_crc_length_verified', path=str(dest), sha256=hashlib.sha256(data).hexdigest(), transferred_bytes=len(raw))
    except Exception as exc:
        rec.update(status='failed', error=type(exc).__name__+': '+str(exc))
        if isinstance(exc,urllib.error.HTTPError) and (exc.code in (401,403,429) or exc.headers.get('Retry-After')):
            stop.set(); rec['shared_stop']=True
    rec['ended_at_utc']=now(); dump(receipt,rec); return rec

def main():
    p=argparse.ArgumentParser();p.add_argument('--start',type=int,default=0);p.add_argument('--stop',type=int,default=80);p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    manifest=BASE/'source-inventory/candidate-member-manifest.json'
    rows=json.loads(manifest.read_text())[a.start:a.stop]
    (BASE/'raw').mkdir(exist_ok=True);(BASE/'acquisition').mkdir(exist_ok=True)
    batch=f'batch-{a.start:03d}-{a.stop:03d}'
    dump(BASE/'acquisition'/f'{batch}.selection.json',{'created_at_utc':now(),'source_manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),'selection_start_inclusive':a.start,'selection_stop_exclusive':a.stop,'rows':rows,'reason':'fixed seeded source frame, before retrieval or human outcomes'})
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        for f in concurrent.futures.as_completed([pool.submit(fetch,r) for r in rows]):
            r=f.result();results.append(r)
            print(len(results),'/',len(rows),r['appid'],r['status'],flush=True)
    dump(BASE/'acquisition'/f'{batch}.receipts.json', sorted(results,key=lambda x:x['game_order_sha256']))
    print('completed',len(results),'successful',sum(r['status'] in ('verified_existing','acquired_crc_length_verified') for r in results),'stop',stop.is_set(),flush=True)

if __name__=='__main__':main()
