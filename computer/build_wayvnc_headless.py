#!/usr/bin/env python3
"""Reproducible local WayVNC virtual-output fix; build/cache on NVMe."""
import argparse,hashlib,json,os,subprocess,tarfile,urllib.request
from pathlib import Path

URL='https://codeload.github.com/any1/wayvnc/tar.gz/refs/tags/v0.9.1'
SHA256='aaaca02d36e54ec6ecf457dc266251946d895ac91521fbabb3470c3c09b3753c'

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--build-dir',type=Path,default=Path('/mnt/nvme/deskpet/data/build/wayvnc-headless-rebuild'))
 parser.add_argument('--install',action='store_true',help='install tested binary in /usr/local/libexec (does not restart services)')
 args=parser.parse_args();root=args.build_dir.resolve()
 if not os.path.ismount('/mnt/nvme') or not root.is_relative_to(Path('/mnt/nvme')):raise SystemExit('Build directory must be on mounted NVMe')
 root.mkdir(parents=True,exist_ok=True);archive=root/'source.tar.gz'
 if not archive.exists():
  with urllib.request.urlopen(URL,timeout=30) as response:archive.write_bytes(response.read(8*1024*1024))
 digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
 if digest(archive)!=SHA256:raise SystemExit('Source archive checksum mismatch')
 source=root/'wayvnc-0.9.1'
 # Re-extract the pinned original before each patch; never layer patches twice.
 with tarfile.open(archive) as tar:tar.extractall(root,filter='data')
 patch=Path(__file__).resolve().with_name('wayvnc-headless.patch')
 subprocess.run(['patch','--batch','-p1','-i',str(patch)],cwd=source,check=True)
 build=root/'build';setup=['meson','setup']+(['--wipe'] if (build/'meson-private/coredata.dat').exists() else [])
 subprocess.run(setup+[str(build),str(source),'--wrap-mode=nofallback','-Dpam=disabled','-Dman-pages=disabled'],check=True)
 subprocess.run(['ninja','-C',str(build),'-j2'],check=True)
 subprocess.run(['meson','test','-C',str(build),'--print-errorlogs'],check=True)
 binary=build/'wayvnc';result={'source_url':URL,'source_sha256':SHA256,'binary_sha256':digest(binary),'meson_tests_passed':True,'installed':False}
 if args.install:
  target=Path('/usr/local/libexec/deskpet-wayvnc-headless');target.parent.mkdir(exist_ok=True)
  staged=target.with_name(target.name+'.new');staged.write_bytes(binary.read_bytes());staged.chmod(0o755);staged.replace(target);result['installed']=True
 (root/'build-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':main()
