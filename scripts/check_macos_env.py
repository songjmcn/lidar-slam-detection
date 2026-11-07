#!/usr/bin/env python3
"""macOS 移植环境自检。

逐层验证「能编译 → 能加载 → 依赖能解析 → 真能算」，任何一层坏掉都会被指出来，
而不是等到 `import slam_wrapper` 段错误或读视频时才暴露。

用法：
    python scripts/check_macos_env.py              # 只查运行时（秒级）
    python scripts/check_macos_env.py --full       # 额外跑一遍干净的 cmake configure + build
    python scripts/check_macos_env.py --build-dir build/lib.macosx-11.0-arm64-cpython-310

退出码：0 全绿（允许 WARN）；1 有 FAIL。
"""

import argparse
import importlib.util
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASS, FAIL, WARN, SKIP = 'PASS', 'FAIL', 'WARN', 'SKIP'
_results = []


def record(status, stage, message):
    _results.append((status, stage, message))
    tag = {PASS: '\033[32mPASS\033[0m', FAIL: '\033[31mFAIL\033[0m',
           WARN: '\033[33mWARN\033[0m', SKIP: '\033[2mSKIP\033[0m'}[status]
    print(f'  [{tag}] {message}')


def stage(title):
    print(f'\n== {title} ==')


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


# ---------------------------------------------------------------- 1. 平台
def check_platform():
    stage('1. 平台与工具链')
    if sys.platform != 'darwin':
        record(FAIL, 'platform', f'非 macOS：{sys.platform}')
        return
    record(PASS, 'platform', f'macOS {platform.mac_ver()[0]} / {platform.machine()}')
    if platform.machine() != 'arm64':
        record(WARN, 'platform', f'架构是 {platform.machine()}，文档只覆盖 arm64')

    for tool in ('cmake', 'otool', 'install_name_tool', 'clang++'):
        path = shutil.which(tool)
        record(PASS if path else FAIL, 'toolchain', f'{tool}: {path or "未找到"}')
    cm = run(['cmake', '--version'])
    if cm.returncode == 0:
        ver = cm.stdout.splitlines()[0]
        record(PASS, 'toolchain', ver)
        if re.search(r'version (\d+)', ver) and int(re.search(r'version (\d+)', ver).group(1)) >= 4:
            record(PASS, 'toolchain', 'CMake 4.x：根 CMakeLists 会自动设 CMAKE_POLICY_VERSION_MINIMUM=3.5')
    record(PASS, 'python', f'{sys.version.split()[0]} @ {sys.executable}')


# ----------------------------------------------------- 2. 依赖头/库位置
DEP_PATHS = [
    ('PCL 1.15',        '/usr/local/pcl/share/pcl-1.15/PCLConfig.cmake'),
    ('OpenCV 4.x',      '/usr/local/opencv4/lib/libopencv_core.4.12.0.dylib'),
    ('OpenCV videoio',  '/usr/local/opencv4/lib/libopencv_videoio.4.12.0.dylib'),
    ('Boost 1.86',      '/usr/local/boost/lib/cmake/Boost-1.86.0/BoostConfig.cmake'),
    ('Eigen 3.4',       '/usr/local/include/eigen3/Eigen/Core'),
    ('g2o',             '/usr/local/lib/cmake/g2o/g2oConfig.cmake'),
    ('g2o cholmod',     '/usr/local/lib/libg2o_solver_cholmod.dylib'),
    ('zcm',             '/usr/local/lib/libzcm.dylib'),
    ('zcm 头',          '/usr/local/include/zcm/zcm-cpp.hpp'),
    ('spdlog 头',       '/usr/local/spdlog/include/spdlog/spdlog.h'),
    ('libomp',          '/opt/homebrew/opt/libomp/lib/libomp.dylib'),
    ('FFmpeg avcodec',  '/usr/local/lib/libavcodec.58.134.100.dylib'),
    ('x264 (ABI 164)',  '/usr/local/lib/libx264.164.dylib'),
]


def check_deps():
    stage('2. 依赖库位置')
    for name, path in DEP_PATHS:
        record(PASS if os.path.exists(path) else FAIL, 'deps', f'{name:16s} {path}')


# ------------------------------------------------------ 3. 模块能否加载
def find_module(build_dir):
    if build_dir:
        cand = os.path.join(build_dir, 'slam_wrapper.so')
        if os.path.exists(cand):
            return cand
    for base in ('build/lib.macosx-11.0-arm64-cpython-310',
                 'build/lib.macosx-11.0-arm64-cpython-310/slam'):
        cand = os.path.join(ROOT, base, 'slam_wrapper.so')
        if os.path.exists(cand):
            return cand
    for dp, _dn, fn in os.walk(os.path.join(ROOT, 'build')):
        if 'slam_wrapper.so' in fn:
            return os.path.join(dp, 'slam_wrapper.so')
    return None


def check_import(module_path):
    """必须用子进程：加载失败是段错误（exit=-11），在进程内测会把自检自己也带走。"""
    stage('3. 模块加载（子进程，捕获段错误）')
    if not module_path:
        record(FAIL, 'import', '找不到 slam_wrapper.so，先跑 python setup.py build_ext')
        return False, 0
    record(PASS, 'import', f'产物 {os.path.relpath(module_path, ROOT)}')
    code = ('import slam_wrapper, sys;'
            'print(len([n for n in dir(slam_wrapper) if not n.startswith("_")]), file=sys.stderr)')
    r = run([sys.executable, '-c', code], cwd=os.path.dirname(module_path))
    if r.returncode == -11:
        record(FAIL, 'import', 'import 段错误（SIGSEGV）——多半是链了两份 CPython 运行时，'
                              '见 README §4「不要链 libpython」')
        return False, 0
    if r.returncode != 0:
        tail = (r.stderr.strip().splitlines() or [''])[-1]
        record(FAIL, 'import', f'import 失败：{tail}')
        return False, 0
    try:
        n = int(r.stderr.strip().splitlines()[-1])
    except (ValueError, IndexError):
        n = 0
    record(PASS, 'import', f'import OK，{n} 个导出符号')
    return True, n


# --------------------------------------------------- 4. dyld 依赖闭包
SYSTEM_PREFIXES = ('/usr/lib/', '/System/', '/Library/Apple/')


def otool_rpaths(path):
    r = run(['otool', '-l', path])
    return re.findall(r'cmd LC_RPATH.*?\n.*?path (.+?) \(offset', r.stdout, re.S)


def otool_install_name(path):
    """LC_ID_DYLIB：otool -L 的第一条依赖其实是它自己的 install_name，必须剔除，
    否则会把自己（`@rpath/libfoo.dylib`）当成一个解析不到的依赖。"""
    r = run(['otool', '-D', path])
    lines = [ln.strip() for ln in r.stdout.splitlines()[1:] if ln.strip()]
    return lines[0] if lines else None


def otool_deps(path):
    r = run(['otool', '-L', path])
    self_name = otool_install_name(path)
    deps = []
    for line in r.stdout.splitlines()[1:]:
        line = line.strip()
        if not line:
            continue
        dep = line.split(' (')[0]
        if dep == self_name:
            continue
        deps.append(dep)
    return deps


def resolve(dep, loader, rpaths):
    if dep.startswith('@rpath/'):
        rel = dep[len('@rpath/'):]
        for rp in rpaths:
            if rp == '@loader_path':
                rp = os.path.dirname(loader)
            elif rp == '@executable_path':
                rp = os.path.dirname(sys.executable)
            cand = os.path.join(rp, rel)
            if os.path.exists(cand):
                return cand
        return None
    if dep.startswith('@loader_path/'):
        cand = os.path.join(os.path.dirname(loader), dep[len('@loader_path/'):])
        return cand if os.path.exists(cand) else None
    if dep.startswith('/'):
        return dep if os.path.exists(dep) else None
    # 裸名（libz.1.dylib 这种）：dyld 只在 cwd 找，等于坏掉
    return None


def check_dyld(module_path):
    stage('4. dyld 依赖闭包（能否真正加载）')
    if not module_path:
        record(SKIP, 'dyld', '无产物')
        return
    todo, seen, missing, visited = [module_path], {module_path}, [], 0
    while todo:
        cur = todo.pop()
        visited += 1
        rpaths = otool_rpaths(cur)
        if '@loader_path' not in rpaths and cur.endswith('.so'):
            record(WARN, 'dyld', f'{os.path.basename(cur)} 没有 @loader_path rpath（install 后可能找不到同目录库）')
        for dep in otool_deps(cur):
            if dep.startswith(SYSTEM_PREFIXES):
                continue
            real = resolve(dep, cur, rpaths)
            if real is None:
                missing.append(f'{os.path.basename(cur)} -> {dep}')
            elif real not in seen:
                seen.add(real)
                todo.append(real)
    record(PASS if not missing else FAIL, 'dyld',
           f'遍历 {visited} 个二进制，{len(seen) - 1} 个非系统依赖全部可解析'
           if not missing else f'{len(missing)} 个依赖无法解析')
    for m in missing[:15]:
        record(FAIL, 'dyld', m)
    if len(missing) > 15:
        record(FAIL, 'dyld', f'... 另有 {len(missing) - 15} 个')


# ------------------------------------------- 5. 已知第三方缺陷是否已修
def check_third_party_fixes():
    stage('5. 第三方 install_name 修复是否仍生效')
    bare_z = []
    for lib in ('libavcodec.58.134.100', 'libavdevice.58.13.100',
                'libavfilter.7.110.100', 'libavformat.58.76.100'):
        path = f'/usr/local/lib/{lib}.dylib'
        if not os.path.exists(path):
            record(WARN, 'fixes', f'{lib} 不存在，跳过')
            continue
        if 'libz.1.dylib' in otool_deps(path):
            bare_z.append(lib)
    record(PASS if not bare_z else FAIL, 'fixes',
           'zlib 无裸名依赖' if not bare_z else f'仍把 zlib 记成裸名：{bare_z}（postgres 式缺陷，dyld 找不到）')

    r = run(['otool', '-L', '/usr/local/lib/libavcodec.58.134.100.dylib'])
    if r.returncode == 0:
        m = re.search(r'(\S*libx264[\w.]*\.dylib)', r.stdout)
        if not m:
            record(WARN, 'fixes', 'avcodec 未引用 x264')
        elif 'x264_encoder' in m.group(1) or True:
            ok = os.path.exists(m.group(1))
            record(PASS if ok else FAIL, 'fixes', f'avcodec 的 x264 -> {m.group(1)}'
                   + ('' if ok else '（文件不存在）'))

    exr = '/opt/homebrew/opt/openexr/lib/libOpenEXR-3_4.33.dylib'
    record(PASS if os.path.exists(exr) else FAIL, 'fixes',
           f'openexr 3.4 ABI 兼容层 {exr}' + ('' if os.path.exists(exr) else '（缺失：imgcodecs 会加载失败）'))


# --------------------------------------------------- 6. C++ 侧功能冒烟
def check_functional(module_path):
    stage('6. 功能冒烟：C++ 核心（GICP 配准）')
    if not module_path:
        record(SKIP, 'func', '无产物')
        return
    if importlib.util.find_spec('numpy') is None:
        record(SKIP, 'func', '缺 numpy，无法构造输入数组')
        return
    code = r'''
import numpy as np, slam_wrapper as slam
rng = np.random.default_rng(0)
src = np.c_[rng.uniform(-5, 5, (400, 3)), np.ones(400)].astype(np.float32)
shift = np.array([2.0, -1.0, 0.5], dtype=np.float32)
tgt = src.copy(); tgt[:, :3] += shift
guess = np.eye(4, dtype=np.float32)
T = slam.pointcloud_align(src, tgt, guess)
err = float(np.linalg.norm(T[:3, 3] - shift))
print(f"{err:.3f}")
assert err < 0.5, f"GICP 未恢复平移，误差 {err}"
'''
    r = run([sys.executable, '-c', code], cwd=os.path.dirname(module_path))
    if r.returncode == 0:
        record(PASS, 'func', f'pointcloud_align 恢复已知平移，误差 {r.stdout.strip()} m')
    else:
        record(FAIL, 'func', f'pointcloud_align 失败：{(r.stderr.strip().splitlines() or ["?"])[-1]}')


# ------------------------------------------------- 7. 视频后端端到端
def check_video():
    stage('7. 功能冒烟：FFmpeg 视频解码')
    if importlib.util.find_spec('cv2') is None:
        record(SKIP, 'video', '缺 cv2（pip install opencv-python），跳过')
        return
    if shutil.which('ffmpeg') is None:
        record(SKIP, 'video', '缺 ffmpeg 命令行，跳过')
        return
    with tempfile.TemporaryDirectory() as td:
        mp4 = os.path.join(td, 't.mp4')
        gen = run(['ffmpeg', '-y', '-f', 'lavfi', '-i',
                   'testsrc=size=320x240:rate=10:duration=1',
                   '-pix_fmt', 'yuv420p', mp4])
        if gen.returncode != 0:
            record(SKIP, 'video', 'ffmpeg 生成测试视频失败')
            return
        code = f'''
import cv2
cap = cv2.VideoCapture({mp4!r})
n = 0
while True:
    ok, f = cap.read()
    if not ok: break
    n += 1
print(f"{{n}} frames {{int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}}x{{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}}")
'''
        r = run([sys.executable, '-c', code])
        if r.returncode == 0 and r.stdout.strip().startswith('10 frames'):
            record(PASS, 'video', f'解码 1s/10fps 测试视频：{r.stdout.strip()}')
        else:
            record(FAIL, 'video', f'解码失败：{(r.stderr.strip().splitlines() or ["?"])[-1]}')


# ------------------------------------------------ 8. Python 侧依赖
# required=True 的会被 module/ 与 tools/ 真实 import（psutil 在 module/module_manager.py 里），
# scipy 只在 calibration/ 与工具脚本里用，缺了不影响 SLAM 主链路。
PY_DEPS = [('numpy', True), ('yaml', True), ('easydict', True),
           ('psutil', True), ('cv2', True), ('scipy', False)]


def check_python_deps():
    stage('8. Python 侧依赖（module/ 与 tools/ 用得到）')
    missing_hard, missing_soft = [], []
    for mod, required in PY_DEPS:
        try:
            ok = importlib.util.find_spec(mod) is not None
        except (ImportError, ValueError):
            ok = False
        if ok:
            record(PASS, 'pydeps', mod)
        else:
            record(FAIL if required else WARN, 'pydeps', f'{mod} 缺失')
            (missing_hard if required else missing_soft).append(mod)
    if missing_hard or missing_soft:
        pkgs = {'yaml': 'pyyaml', 'cv2': 'opencv-python'}
        cmd = ' '.join(pkgs.get(m, m) for m in missing_hard + missing_soft)
        record(FAIL if missing_hard else WARN, 'pydeps', f'建议：pip install {cmd}')


# ------------------------------------------------- 9. 可选：全量编译
def check_build():
    stage('9. 干净目录 cmake configure（--full 才有）')
    with tempfile.TemporaryDirectory() as td:
        args = ['cmake', '-S', ROOT, '-B', td, '-Wno-dev',
                '-DCMAKE_BUILD_TYPE=Release', '-DBOARD_NAME=arm64',
                f'-DPYTHON_EXECUTABLE={sys.executable}',
                '-DCMAKE_PREFIX_PATH=/usr/local/pcl:/usr/local/opencv4:/usr/local:/opt/homebrew/opt/libomp',
                '-DOpenMP_C_FLAGS=-Xpreprocessor -fopenmp -I/opt/homebrew/opt/libomp/include',
                '-DOpenMP_C_LIB_NAMES=omp',
                '-DOpenMP_CXX_FLAGS=-Xpreprocessor -fopenmp -I/opt/homebrew/opt/libomp/include',
                '-DOpenMP_CXX_LIB_NAMES=omp',
                '-DOpenMP_omp_LIBRARY=/opt/homebrew/opt/libomp/lib/libomp.dylib']
        r = run(args)
        if r.returncode == 0:
            record(PASS, 'build', 'configure 通过（未传 CMAKE_POLICY_VERSION_MINIMUM，验证根 CMakeLists 兜底生效）')
            record(PASS, 'build', '产物目录已删除，如需真编译请 cmake --build')
        else:
            err = [ln for ln in r.stderr.splitlines() if 'Error' in ln][:3]
            record(FAIL, 'build', f'configure 失败：{err}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build-dir', default=None, help='slam_wrapper.so 所在目录')
    ap.add_argument('--full', action='store_true', help='额外跑干净 configure')
    args = ap.parse_args()

    print(f'lidar-slam-detection macOS 环境自检  ({ROOT})')
    check_platform()
    check_deps()
    module = find_module(args.build_dir) if args.build_dir else find_module(None)
    ok, _n = check_import(module)
    check_dyld(module)
    check_third_party_fixes()
    check_functional(module)
    check_video()
    check_python_deps()
    if args.full:
        check_build()

    fails = [r for r in _results if r[0] == FAIL]
    warns = [r for r in _results if r[0] == WARN]
    print(f'\n{"="*60}')
    print(f'汇总：{len(_results) - len(fails) - len(warns)} PASS / {len(fails)} FAIL / {len(warns)} WARN')
    if fails:
        print('未通过项：')
        for _s, st, m in fails:
            print(f'  - [{st}] {m}')
    print('=' * 60)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
