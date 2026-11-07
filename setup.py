import os
import re
import sys
import platform
import subprocess

from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext
from distutils.version import LooseVersion

from hardware.platform_common import BOARD_NAME, MACHINE

class CMakeExtension(Extension):
    def __init__(self, name, sourcedir=''):
        Extension.__init__(self, name, sources=[])
        self.sourcedir = os.path.abspath(sourcedir)


class CMakeBuild(build_ext):
    def run(self):
        try:
            out = subprocess.check_output(['cmake', '--version'])
        except OSError:
            raise RuntimeError("CMake must be installed to build the following extensions: " +
                               ", ".join(e.name for e in self.extensions))

        for ext in self.extensions:
            self.build_extension(ext)

    def build_extension(self, ext):
        extdir = os.path.abspath(os.path.dirname(self.get_ext_fullpath(ext.name)))
        # required for auto-detection of auxiliary "native" libs
        if not extdir.endswith(os.path.sep):
            extdir += os.path.sep

        cmake_args = ['-DCMAKE_LIBRARY_OUTPUT_DIRECTORY=' + extdir,
                      '-DPYTHON_EXECUTABLE=' + sys.executable]

        cfg = 'Debug' if self.debug else 'Release'
        build_args = ['--config', cfg]

        cmake_args += ['-Wno-dev', '-DCMAKE_BUILD_TYPE=' + cfg, '-DBOARD_NAME=' + BOARD_NAME]

        env = os.environ.copy()

        if sys.platform == 'darwin':
            # CMake >= 4 rejects cmake_minimum_required(VERSION < 3.5), and a few
            # vendored CMakeLists (tools/*/pybind11, fast_gicp/thirdparty/*) still
            # declare 2.8 / 3.4.  The in-tree ones are already bumped to 3.5; this
            # covers anything vendored we do not own.
            cmake_args += ['-DCMAKE_POLICY_VERSION_MINIMUM=3.5']
            # /usr/local is NOT searched by default on macOS, but PCL, OpenCV, Boost,
            # g2o and zcm are all installed there.
            cmake_args += ['-DCMAKE_PREFIX_PATH=' + env.get(
                'LIDAR_CMAKE_PREFIX_PATH',
                '/usr/local/pcl:/usr/local/opencv4:/usr/local:/opt/homebrew/opt/libomp')]
            # Apple clang ships without OpenMP; libomp is a brew keg-only formula.
            libomp = env.get('LIBOMP_PREFIX', '/opt/homebrew/opt/libomp')
            cmake_args += [
                '-DOpenMP_C_FLAGS=-Xpreprocessor -fopenmp -I' + libomp + '/include',
                '-DOpenMP_C_LIB_NAMES=omp',
                '-DOpenMP_CXX_FLAGS=-Xpreprocessor -fopenmp -I' + libomp + '/include',
                '-DOpenMP_CXX_LIB_NAMES=omp',
                '-DOpenMP_omp_LIBRARY=' + libomp + '/lib/libomp.dylib',
            ]
            # Headers outside the default include path: spdlog only ships under
            # /usr/local/spdlog/include (zcm is already at /usr/local/include/zcm).
            for var, extra in (('CPATH', ['/usr/local/spdlog/include', '/usr/local/include']),
                               ('LIBRARY_PATH', ['/usr/local/lib'])):
                env[var] = os.pathsep.join(
                    extra + ([env[var]] if env.get(var) else []))

        if BOARD_NAME in ["AGX-Orin-32GB", "NX-Orin"]:
            build_thread = 8
        else:
            build_thread = 4

        os.system(''' echo "Board {}, use {} threads for building" '''.format(BOARD_NAME, build_thread))
        build_args += ['--', '-j'+str(build_thread)]

        env['CXXFLAGS'] = '{} -DVERSION_INFO=\\"{}\\"'.format(env.get('CXXFLAGS', ''),
                                                              self.distribution.get_version())
        if not os.path.exists(self.build_temp):
            os.makedirs(self.build_temp)
        subprocess.check_call(['cmake', ext.sourcedir] + cmake_args, cwd=self.build_temp, env=env)
        # env must be forwarded here too: CPATH/LIBRARY_PATH are read by the
        # compiler at build time, not by the configure step.
        subprocess.check_call(['cmake', '--build', '.'] + build_args, cwd=self.build_temp, env=env)

        if sys.platform == 'darwin':
            self.bundle_macos_dylibs(extdir)

    def bundle_macos_dylibs(self, extdir):
        """Make the built extension self-contained.

        CMake puts every librtkm/libfast_lio/... next to the module in extdir and
        records an rpath pointing at that absolute path, which only works while
        build/temp.* is still on disk. Copy the dylibs into build_lib (install_lib
        copies that whole tree) and add @loader_path so the installed module
        resolves them from its own directory.
        """
        import glob
        import shutil

        dylibs = glob.glob(os.path.join(extdir, '*.dylib'))
        if not dylibs:
            return
        os.makedirs(self.build_lib, exist_ok=True)
        same_dir = os.path.realpath(extdir) == os.path.realpath(self.build_lib)
        if not same_dir:
            for lib in dylibs:
                shutil.copy2(lib, os.path.join(self.build_lib, os.path.basename(lib)))

        module = os.path.join(extdir, 'slam_wrapper.so')
        if os.path.exists(module):
            rpaths = subprocess.run(['otool', '-l', module], capture_output=True,
                                    text=True).stdout
            if '@loader_path' not in rpaths:
                subprocess.check_call(['install_name_tool', '-add_rpath', '@loader_path', module])


def spconv_data_files():
    """libspconv pre-built binaries only exist for the Linux/Jetson layouts
    (aarch64/, x86_64/). On macOS the directory is absent and setup() would fail
    with "no such file or directory" at install time, so skip it there."""
    path = f'sensor_driver/inference/libspconv/lib/{MACHINE}/libspconv.so'
    return [('lib/', [path])] if os.path.exists(path) else []


setup(
    name='perception',
    version='1.0.0',
    author='LiangWang',
    author_email='15lwang@alumni.tongji.edu.cn',
    description='LiDAR SLAM & Detection',
    long_description='',
    ext_modules=[CMakeExtension('perception')],
    data_files=spconv_data_files(),
    cmdclass=dict(build_ext=CMakeBuild),
    zip_safe=False,
)
