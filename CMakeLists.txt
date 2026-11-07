# CMake >= 4 dropped compatibility with cmake_minimum_required(VERSION < 3.5).
# Every in-tree CMakeLists is on 3.5+, but some vendored subtrees
# (fast_gicp/thirdparty/*, tools/*/pybind11) can still be pulled in by option
# switches, so give the whole tree a floor before the first version check runs.
# Must be set before cmake_minimum_required() for it to take effect.
if(CMAKE_VERSION VERSION_GREATER_EQUAL 4.0 AND NOT DEFINED CMAKE_POLICY_VERSION_MINIMUM)
    set(CMAKE_POLICY_VERSION_MINIMUM 3.5 CACHE STRING "Compatibility floor for legacy CMakeLists" FORCE)
endif()
cmake_minimum_required(VERSION 3.6)
project(perception)
set(Boost_USE_STATIC_LIBS ON)
add_subdirectory(${CMAKE_SOURCE_DIR}/third_party/pybind11)
include_directories(
    ${CMAKE_SOURCE_DIR}/third_party/readerwriterqueue
)

message(STATUS "BOARD_NAME: ${BOARD_NAME}")
EXECUTE_PROCESS(COMMAND uname -m COMMAND tr -d '\n' OUTPUT_VARIABLE ARCHITECTURE)
if(${ARCHITECTURE} STREQUAL "x86_64")
    add_definitions(-DPLATFORM_X86_64)
else()
    add_definitions(-DPLATFORM_AARCH64)
endif()

list(APPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/slam/cmake)

# macOS port: <sys/prctl.h> is Linux-only, but the code base only uses it for
# PR_SET_NAME (thread naming). Prepend a shim directory so those includes
# resolve; on Linux the real system header wins as usual.
if(APPLE)
    include_directories(BEFORE ${CMAKE_CURRENT_SOURCE_DIR}/third_party/macos_compat)
endif()

add_subdirectory(proto)
# macOS port: the full sensor_driver tree (inference/drivers/calibration) needs CUDA,
# spconv and hardware SDKs. slam/* however hard-depends on sensor_driver/common_lib
# targets (logging, network_driver, cpp_utils) for Logger.h / SystemUtils.h / UTMProjector.h,
# so build only that sub-tree.
#add_subdirectory(sensor_driver)
add_subdirectory(sensor_driver/common_lib)
add_subdirectory(slam)
