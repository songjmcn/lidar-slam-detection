# macOS (arm64) 移植说明

本项目原始目标平台是 Ubuntu 20.04，这里记录在本机原生编译/运行的全部改动。
Linux 行为不受影响：所有改动都用 `__APPLE__` / `__GLIBCXX__` / `#if defined(__linux__)`
做平台分支，或只是补上原本靠传递包含才拿到的头文件。

## 1. 依赖安装位置

| 依赖 | 版本 | 位置 | 说明 |
| --- | --- | --- | --- |
| PCL | 1.15.0 | `/usr/local/pcl` | 自编译，`-DBoost_USE_STATIC_LIBS=ON`，关 VTK |
| OpenCV | 4.12.0 | `/usr/local/opencv4` | 含 contrib |
| Boost | 1.86.0 | `/usr/local/boost` | 纯静态（`*-mt-a64.a`），链接时会有 duplicate 警告，无害 |
| Eigen | 3.4.0 | `/usr/local/include/eigen3` | |
| g2o | 自编译 | `/usr/local` | 需 `G2O_USE_CHOLMOD/CSPARSE=ON` |
| zcm | 自编译 | `/usr/local` | brew 无公式，见 §3 |
| libomp | 23.1.5 | `/opt/homebrew/opt/libomp` | Apple clang 不带 OpenMP |

`/usr/local` 不在 CMake 默认搜索路径里，必须在 `CMAKE_PREFIX_PATH` 中显式列出。

Python 侧（`module/`、`tools/` 里的脚本会用）另需：

```bash
pip install numpy pyyaml easydict opencv-python scipy psutil
```

注意 `slam_wrapper` 本身不依赖 python 的 `cv2`，视频解码走 C++ 里的 `opencv_videoio`；
但 `tools/` 与 `module/` 的脚本会 `import cv2`。

## 2. 配置与编译

```bash
cmake -S . -B build_mac -Wno-dev -DCMAKE_BUILD_TYPE=Release -DBOARD_NAME=arm64 \
  -DPYTHON_EXECUTABLE=$(which python3) \
  -DCMAKE_PREFIX_PATH="/usr/local/pcl:/usr/local/opencv4:/usr/local:/opt/homebrew/opt/libomp" \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
  -DOpenMP_C_FLAGS="-Xpreprocessor -fopenmp -I/opt/homebrew/opt/libomp/include" \
  -DOpenMP_C_LIB_NAMES=omp \
  -DOpenMP_CXX_FLAGS="-Xpreprocessor -fopenmp -I/opt/homebrew/opt/libomp/include" \
  -DOpenMP_CXX_LIB_NAMES=omp \
  -DOpenMP_omp_LIBRARY=/opt/homebrew/opt/libomp/lib/libomp.dylib

CPATH="/usr/local/include:/usr/local/spdlog/include" \
cmake --build build_mac --parallel 4
```

- `CMAKE_POLICY_VERSION_MINIMUM=3.5`：**已由根 `CMakeLists.txt` 自动设置**（仅 CMake ≥ 4 时生效），
  命令行上不再必须传。树内所有 `cmake_minimum_required` 已统一到 3.5，少数 vendored 子树
  （`slam/thirdparty/fast_gicp/thirdparty/*`、`tools/*/pybind11`）由这个下限兜底。
- 用 `CPATH` 而不是 `-DCMAKE_CXX_FLAGS=-I...`：各子目录的
  `set(CMAKE_CXX_FLAGS "-std=c++17")` 会覆盖掉全局变量。
- `proto/detection.pb.cc` 必须用与 `google/protobuf` 头**同版本**的 protoc 重新生成，
  否则报 `no matching constructor for initialization of CachedSize`。

产物：`build_mac/slam/slam_wrapper.so`（Python 扩展）+ `build_mac/slam/*.dylib`。

### 2.1 用 setup.py 构建 Python 扩展

```bash
conda activate LSD
python setup.py build_ext      # 或 python setup.py install
```

`setup.py` 在 macOS 上会自动补上 `CMAKE_POLICY_VERSION_MINIMUM=3.5`、`CMAKE_PREFIX_PATH`、
libomp 的 5 个 OpenMP 变量，以及编译期的 `CPATH`（`/usr/local/spdlog/include`、
`/usr/local/include`）和 `LIBRARY_PATH`。默认路径可用环境变量
`LIDAR_CMAKE_PREFIX_PATH` / `LIBOMP_PREFIX` 覆盖。

两点注意：
- `CPATH` / `LIBRARY_PATH` **必须在 `cmake --build` 时也传入**（编译器读取），只在 configure
  阶段设置时会在 `Logger.h:6 fatal error: 'spdlog/spdlog.h' file not found` 处失败。
- `libspconv.so` 的 `data_files` 在对应目录不存在时会跳过；macOS 只有 `aarch64/`、`x86_64/`
  两套 Linux 预编译包，`MACHINE=arm64` 会直接命中 `FileNotFoundError`。

`build_ext` 结束后会用 `install_name_tool -add_rpath @loader_path` 给模块补一条相对 rpath，
并把 15 个 `lib*.dylib` 一起放进 `build/lib.macosx-*/`。`install_lib` 会整棵拷贝该目录，
所以 `python setup.py install` 装出来的模块**自包含**——不依赖 `build/` 里的绝对路径。

## 2.2 CMake 4.x 的策略下限

CMake 4 移除了对 `cmake_minimum_required(VERSION < 3.5)` 的兼容。仓库内 13 个 CMakeLists
（`slam/localization/map_render`、`sensor_driver/{calibration,inference,ins_driver,lidar_driver,radar_driver}`、
`tools/recv_sample{,/network}`、`tools/rosbag_proxy/src/rosbag_proxy{,/network}`、
`tools/rosbag_to_pkl/rosbag_reader/msg/{livox_ros_driver,monitor_msgs,velodyne_msgs}`）
已统一 bump 到 3.5；vendored 子树（`slam/thirdparty/fast_gicp/thirdparty/*`、`tools/*/pybind11`）保持原样。

根 `CMakeLists.txt` 另有一道兜底，在本文件第一个 `cmake_minimum_required()` 之前执行：

```cmake
if(CMAKE_VERSION VERSION_GREATER_EQUAL 4.0 AND NOT DEFINED CMAKE_POLICY_VERSION_MINIMUM)
    set(CMAKE_POLICY_VERSION_MINIMUM 3.5 CACHE STRING "Compatibility floor for legacy CMakeLists" FORCE)
endif()
```

这样即使某个 vendored 子树被选项引入，也不会再触发 policy 报错。

## 3. 运行时依赖修复（都是第三方库自身的 install_name 缺陷）

**zcm**：brew 没有公式，需源码构建，且 `--use-serial` 必须关闭
（`transport_serial.cpp` 依赖 `linux/usbdevice_fs.h`）。装好后把
`include/zcm` 与 `lib/libzcm.dylib` 放进 `/usr/local`。

**FFmpeg 4.4 的 x264 路径写死成 brew 前缀**，而 brew 的 x264 已升到只导出
`x264_encoder_open_165`。本机 `/usr/local/lib/libx264.164.dylib` 才是匹配的 ABI：

```bash
for f in libavcodec.58.134.100 libavdevice.58.13.100 libavfilter.7.110.100 libavformat.58.76.100; do
  sudo install_name_tool -change /opt/homebrew/opt/x264/lib/libx264.164.dylib \
       /usr/local/lib/libx264.164.dylib /usr/local/lib/$f.dylib
  sudo codesign --force --sign - /usr/local/lib/$f.dylib   # arm64 必须重签
done
```

注意**不能用软链**把 `libx264.164.dylib` 指向 homebrew 的 `.165`：x264 导出带版本号
的符号，会报 `Symbol not found: _x264_encoder_open_164`。

**libz 裸名**：同样 4 个库把 zlib 记成 `libz.1.dylib`（dyld 只在 cwd 找）：

```bash
sudo install_name_tool -change libz.1.dylib /usr/lib/libz.1.dylib /usr/local/lib/<lib>.dylib
sudo codesign --force --sign - /usr/local/lib/<lib>.dylib
```

**openexr**：`opencv_imgcodecs`（以及依赖它的 `opencv_videoio`）需要
`libOpenEXR-3_4.33.dylib` 等 4 个库。brew 已升到 3.5.x（命名空间 `Imf_3_5`），
用软链替换会 ABI 断裂（`Symbol not found: __ZN7Imf_3_410OutputFile11writePixelsEi`）。
正解：源码装 openexr 3.4.3 到 `/usr/local/openexr3.4`，再在
`/opt/homebrew/opt/openexr/lib/` 下建 4 个软链；或重编 OpenCV 时加 `-DWITH_OPENEXR=OFF`。

## 4. 源码层改动摘要

- `third_party/macos_compat/sys/prctl.h`：新增。macOS 无 `prctl`，项目只用
  `PR_SET_NAME` 命名线程，shim 转 `pthread_setname_np`。根 `CMakeLists.txt` 在
  `if(APPLE)` 下把该目录加到 include 最前。
- `sensor_driver/common_lib/network_driver/SerialDriver.cpp`：串口自定义波特率
  走 `IOSSIOSPEED`（Linux 走 `TIOCSSERIAL`）。
- `sensor_driver/common_lib/cpp_utils/SystemUtils.cpp`：Boost.Stacktrace 改用非
  addr2line 后端；`setSelfThreadAffinity` 用 `thread_policy_set(THREAD_AFFINITY_POLICY)`。
- `slam/mapping/fastlio/include/ivox3d/ivox3d*.h`：libc++ 没有 `std::execution`
  并行策略，用 `FLIO_FOR_EACH` 宏降级为串行 `std::for_each`；修 `template` 关键字误用与
  `operator<` 的 const 缺失。
- `slam/cmake/FindOpenCV2.cmake`：加 `OPENCV_PREFIX` 缓存变量与
  `find_package_handle_standard_args`；库列表为 core/imgproc/features2d/calib3d/
  flann/imgcodecs/**videoio**。`opencv_highgui` 不链接（本项目不开窗口），
  而 `opencv_videoio` 是视频解码（`cv::VideoCapture` 的 FFmpeg 后端）的承载模块。
- `slam/mapping/rtkm`、`slam/mapping/fastlio`：`target_link_libraries` 补 `g2o_backend`。
  Linux 允许 .so 留未定义符号，macOS 的 ld 默认拒绝。
- `slam/CMakeLists.txt`：macOS 下 `slam_wrapper` **不再链接 `${PYTHON_LIBRARIES}`**。
  conda 的 `python3` 把 CPython 静态编进可执行文件并导出 `_Py*` 符号，pybind11 在
  macOS 上用 `-undefined dynamic_lookup` 就够了。如果再把 `libpython3.9.dylib` 链接进
  bundle，进程里会存在**两份 CPython 运行时**（各自的 `_PyRuntime`），模块的
  `PyGILState_*` / `PyEval_RestoreThread` 拿到 NULL 的 thread state，`import` 直接
  在 `take_gil + 92` 段错误。
- 其它单点补头：`DBoW2/FORB.cpp`、`ORBSLAM/src/ORBmatcher.cc`（`<stdint-gcc.h>` →
  `<cstdint>`）、`map_render.cpp`（`<boost/optional.hpp>`）、`graph_slam.hpp`
  （`<Eigen/Geometry>`）、`slam.cpp`（`<boost/algorithm/string/replace.hpp>`）。

## 5. 验证

一条命令跑完所有层次的自检（推荐）：

```bash
conda activate LSD
python scripts/check_macos_env.py          # 运行时自检，秒级
python scripts/check_macos_env.py --full    # 额外跑一次干净目录 configure
```

自检按「能编译 → 能加载 → 依赖能解析 → 真能算」分层，任一层坏掉都会被点名，各层含义：

| 层 | 检查内容 | 坏了会怎样 |
|---|---|---|
| 1–2 | 工具链版本、13 个依赖库/头的实际路径 | CMake 阶段就找不到 PCL/OpenCV |
| 3 | 子进程 `import slam_wrapper`（专门捕获 SIGSEGV） | 加载即段错误（两份 CPython 运行时） |
| 4 | 递归遍历 99 个二进制的 `otool -L` 闭包 | `import` 报 `Library not loaded: @rpath/...` |
| 5 | libz 裸名 / x264 ABI / openexr 3.4 三处第三方修复是否还生效 | 读视频时才炸，或升级 brew 后静默回归 |
| 6 | `pointcloud_align` 恢复已知平移（真实 GICP 计算） | C++ 核心跑通但数值不对 |
| 7 | FFmpeg 解码 1s/10fps 测试视频 | `cv::VideoCapture` 打不开文件 |
| 8 | numpy/yaml/easydict/cv2 等 Python 依赖 | `module/`、`tools/` 里的脚本 import 失败 |
| 9 | 干净目录 configure（`--full`） | 根 CMakeLists 的政策兜底失效 |

手工最小验证：

```bash
# 模块能导入（46 个导出符号）
cd build_mac/slam && python3 -c "import slam_wrapper; print('ok')"

# 视频解码可用（FFmpeg 后端）
ffmpeg -y -f lavfi -i testsrc=size=320x240:rate=10:duration=1 -pix_fmt yuv420p /tmp/t.mp4
clang++ -std=c++17 -I/usr/local/opencv4/include/opencv4 -L/usr/local/opencv4/lib \
  -Wl,-rpath,/usr/local/opencv4/lib -lopencv_videoio -lopencv_imgcodecs -lopencv_core \
  video_test.cpp -o video_test && ./video_test /tmp/t.mp4
# 期望输出: opened backend=FFMPEG frames=10 fps=10.0 320x240
```
