cmake_minimum_required(VERSION 3.5 FATAL_ERROR)
project(rtkm)

set(CMAKE_C_FLAGS "-Wall")
set(CMAKE_CXX_FLAGS "-std=c++17")
set(CMAKE_BUILD_TYPE "Release")


include_directories (/usr/local/include)
link_directories(/usr/local/lib)

find_package(Eigen3 REQUIRED)

include_directories(
    ${CMAKE_CURRENT_SOURCE_DIR}/../../common
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    SYSTEM ${EIGEN3_INCLUDE_DIR}
)

add_library(rtkm SHARED
    src/rtkm.cpp
)

target_include_directories(rtkm
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>/include)

target_link_libraries(rtkm
    map_common
    # rtkm orchestrates the graph backend (init_/deinit_*_node, graph_optimization).
    # On Linux those symbols were left undefined in the .so and resolved when the
    # main executable linked everything; macOS's ld refuses that for dylibs.
    g2o_backend
)
