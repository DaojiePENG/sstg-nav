#ifndef functions_H
#define functions_H
#include <vector>
#include <stdlib.h>
#include <time.h>
#include <math.h>
#include "nav_msgs/msg/occupancy_grid.hpp"
#include "geometry_msgs/msg/point.hpp"
#include "visualization_msgs/msg/marker.hpp"

class rdm{
int i;
public:
rdm();
float randomize();
};

float Norm( std::vector<float> , std::vector<float> );
float sign(float );
std::vector<float> Nearest(  std::vector< std::vector<float>  > , std::vector<float> );
std::vector<float> Steer(  std::vector<float>, std::vector<float>, float );
bool isInsideMap(const nav_msgs::msg::OccupancyGrid &, const std::vector<float> &);
int gridValue(nav_msgs::msg::OccupancyGrid &,std::vector<float>);
int ObstacleFree(std::vector<float> , std::vector<float> & , nav_msgs::msg::OccupancyGrid);
#endif
