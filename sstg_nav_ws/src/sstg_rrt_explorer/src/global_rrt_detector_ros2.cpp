#include "rclcpp/rclcpp.hpp"
#include "nav_msgs/msg/occupancy_grid.hpp"
#include "geometry_msgs/msg/point_stamped.hpp"
#include "visualization_msgs/msg/marker.hpp"
#include "functions.h"
#include "mtrand.h"
#include <vector>
#include <cmath>
#include <algorithm>

class GlobalRRTDetector : public rclcpp::Node
{
public:
    GlobalRRTDetector() : Node("global_rrt_detector")
    {
        this->declare_parameter("eta", 2.0);
        this->declare_parameter("map_topic", "/map");
        this->declare_parameter("status_log_interval", 2.0);

        eta_ = this->get_parameter("eta").as_double();
        status_log_interval_ = this->get_parameter("status_log_interval").as_double();
        std::string map_topic = this->get_parameter("map_topic").as_string();
        auto map_qos = rclcpp::QoS(rclcpp::KeepLast(1)).reliable().transient_local();

        map_sub_ = this->create_subscription<nav_msgs::msg::OccupancyGrid>(
            map_topic, map_qos, std::bind(&GlobalRRTDetector::mapCallback, this, std::placeholders::_1));

        clicked_sub_ = this->create_subscription<geometry_msgs::msg::PointStamped>(
            "/clicked_point", 10, std::bind(&GlobalRRTDetector::clickedCallback, this, std::placeholders::_1));

        targets_pub_ = this->create_publisher<geometry_msgs::msg::PointStamped>("/detected_points", 10);
        shapes_pub_ = this->create_publisher<visualization_msgs::msg::Marker>("shapes", 10);

        RCLCPP_INFO(this->get_logger(), "Global RRT detector initialized");
    }

    void run()
    {
        while (mapData_.data.empty() && rclcpp::ok()) {
            rclcpp::spin_some(this->get_node_base_interface());
            rclcpp::sleep_for(std::chrono::milliseconds(100));
        }

        initMarkers();

        RCLCPP_INFO(this->get_logger(), "Waiting for 5 clicked points: 4 corners + 1 seed point");
        while (clicked_points_.size() < 5 && rclcpp::ok()) {
            points_.header.stamp = this->now();
            points_.points = clicked_points_;
            shapes_pub_->publish(points_);
            rclcpp::spin_some(this->get_node_base_interface());
            rclcpp::sleep_for(std::chrono::milliseconds(50));
        }

        initializeSearchArea();
        points_.points.clear();
        points_.header.stamp = this->now();
        shapes_pub_->publish(points_);

        initialized_ = true;
        last_status_log_ = this->now();
        timer_ = this->create_wall_timer(
            std::chrono::milliseconds(10),
            std::bind(&GlobalRRTDetector::rrtLoop, this));

        rclcpp::spin(this->shared_from_this());
    }

private:
    void initMarkers()
    {
        points_.header.frame_id = mapData_.header.frame_id;
        line_.header.frame_id = mapData_.header.frame_id;

        points_.ns = "global_rrt_points";
        line_.ns = "global_rrt_tree";
        points_.id = 0;
        line_.id = 1;

        points_.type = visualization_msgs::msg::Marker::POINTS;
        line_.type = visualization_msgs::msg::Marker::LINE_LIST;
        points_.action = visualization_msgs::msg::Marker::ADD;
        line_.action = visualization_msgs::msg::Marker::ADD;
        points_.pose.orientation.w = 1.0;
        line_.pose.orientation.w = 1.0;
        line_.scale.x = 0.03;
        line_.scale.y = 0.03;
        points_.scale.x = 0.25;
        points_.scale.y = 0.25;

        line_.color.r = 9.0 / 255.0;
        line_.color.g = 91.0 / 255.0;
        line_.color.b = 236.0 / 255.0;
        line_.color.a = 1.0;

        points_.color.r = 1.0;
        points_.color.g = 0.2;
        points_.color.b = 0.2;
        points_.color.a = 1.0;
    }

    void initializeSearchArea()
    {
        const auto &seed = clicked_points_[4];

        float min_x = std::min({clicked_points_[0].x, clicked_points_[1].x, clicked_points_[2].x, clicked_points_[3].x});
        float max_x = std::max({clicked_points_[0].x, clicked_points_[1].x, clicked_points_[2].x, clicked_points_[3].x});
        float min_y = std::min({clicked_points_[0].y, clicked_points_[1].y, clicked_points_[2].y, clicked_points_[3].y});
        float max_y = std::max({clicked_points_[0].y, clicked_points_[1].y, clicked_points_[2].y, clicked_points_[3].y});

        min_x = std::min(min_x, static_cast<float>(seed.x));
        max_x = std::max(max_x, static_cast<float>(seed.x));
        min_y = std::min(min_y, static_cast<float>(seed.y));
        max_y = std::max(max_y, static_cast<float>(seed.y));

        const float margin = std::max(static_cast<float>(eta_ * 2.0), 0.5f);
        min_x -= margin;
        max_x += margin;
        min_y -= margin;
        max_y += margin;

        init_map_x_ = max_x - min_x;
        init_map_y_ = max_y - min_y;
        x_start_x_ = (min_x + max_x) * 0.5f;
        x_start_y_ = (min_y + max_y) * 0.5f;
        tree_.clear();
        tree_.push_back({static_cast<float>(seed.x), static_cast<float>(seed.y)});
        line_.points.clear();

        RCLCPP_INFO(
            this->get_logger(),
            "Global RRT area initialized: bbox=[%.2f, %.2f] x [%.2f, %.2f], seed=(%.2f, %.2f), eta=%.2f",
            min_x, max_x, min_y, max_y, seed.x, seed.y, eta_);
    }

    void expandSearchArea(const geometry_msgs::msg::Point &p)
    {
        const float margin = std::max(static_cast<float>(eta_ * 2.0), 0.5f);
        const float current_min_x = x_start_x_ - (init_map_x_ * 0.5f);
        const float current_max_x = x_start_x_ + (init_map_x_ * 0.5f);
        const float current_min_y = x_start_y_ - (init_map_y_ * 0.5f);
        const float current_max_y = x_start_y_ + (init_map_y_ * 0.5f);

        float min_x = std::min(current_min_x, static_cast<float>(p.x));
        float max_x = std::max(current_max_x, static_cast<float>(p.x));
        float min_y = std::min(current_min_y, static_cast<float>(p.y));
        float max_y = std::max(current_max_y, static_cast<float>(p.y));

        min_x -= margin;
        max_x += margin;
        min_y -= margin;
        max_y += margin;

        init_map_x_ = max_x - min_x;
        init_map_y_ = max_y - min_y;
        x_start_x_ = (min_x + max_x) * 0.5f;
        x_start_y_ = (min_y + max_y) * 0.5f;

        RCLCPP_INFO(
            this->get_logger(),
            "Global RRT area expanded by clicked point: bbox=[%.2f, %.2f] x [%.2f, %.2f], clicked=(%.2f, %.2f)",
            min_x, max_x, min_y, max_y, p.x, p.y);
    }

    void mapCallback(const nav_msgs::msg::OccupancyGrid::SharedPtr msg)
    {
        mapData_ = *msg;
    }

    void clickedCallback(const geometry_msgs::msg::PointStamped::SharedPtr msg)
    {
        geometry_msgs::msg::Point p;
        p.x = msg->point.x;
        p.y = msg->point.y;
        p.z = msg->point.z;

        if (initialized_) {
            expandSearchArea(p);
            return;
        }

        if (clicked_points_.size() >= 5) {
            return;
        }

        clicked_points_.push_back(p);
    }

    void publishStatusIfDue()
    {
        const auto now = this->now();
        if ((now - last_status_log_).seconds() < status_log_interval_) {
            return;
        }

        RCLCPP_INFO(
            this->get_logger(),
            "Global RRT stats: tree_nodes=%zu edges=%zu free=%zu frontier=%zu blocked=%zu",
            tree_.size(), line_.points.size() / 2, free_count_, frontier_count_, obstacle_count_);

        free_count_ = 0;
        frontier_count_ = 0;
        obstacle_count_ = 0;
        last_status_log_ = now;
    }

    void rrtLoop()
    {
        if (mapData_.data.empty() || tree_.empty()) {
            return;
        }

        std::vector<float> x_rand, x_nearest, x_new;

        float xr = (random_gen_() * init_map_x_) - (init_map_x_ * 0.5f) + x_start_x_;
        float yr = (random_gen_() * init_map_y_) - (init_map_y_ * 0.5f) + x_start_y_;
        x_rand.push_back(xr);
        x_rand.push_back(yr);

        x_nearest = Nearest(tree_, x_rand);
        x_new = Steer(x_nearest, x_rand, eta_);

        int checking = ObstacleFree(x_nearest, x_new, mapData_);

        if (checking == -1) {
            ++frontier_count_;

            geometry_msgs::msg::PointStamped exploration_goal;
            exploration_goal.header.stamp = this->now();
            exploration_goal.header.frame_id = mapData_.header.frame_id;
            exploration_goal.point.x = x_new[0];
            exploration_goal.point.y = x_new[1];
            exploration_goal.point.z = 0.0;

            geometry_msgs::msg::Point p;
            p.x = x_new[0];
            p.y = x_new[1];
            p.z = 0.0;
            points_.points.clear();
            points_.points.push_back(p);
            points_.header.stamp = this->now();
            shapes_pub_->publish(points_);
            targets_pub_->publish(exploration_goal);
        }
        else if (checking == 1) {
            ++free_count_;
            tree_.push_back(x_new);

            geometry_msgs::msg::Point p;
            p.x = x_new[0];
            p.y = x_new[1];
            p.z = 0.0;
            line_.points.push_back(p);
            p.x = x_nearest[0];
            p.y = x_nearest[1];
            line_.points.push_back(p);
        }
        else {
            ++obstacle_count_;
        }

        line_.header.stamp = this->now();
        shapes_pub_->publish(line_);
        publishStatusIfDue();
    }

    rclcpp::Subscription<nav_msgs::msg::OccupancyGrid>::SharedPtr map_sub_;
    rclcpp::Subscription<geometry_msgs::msg::PointStamped>::SharedPtr clicked_sub_;
    rclcpp::Publisher<geometry_msgs::msg::PointStamped>::SharedPtr targets_pub_;
    rclcpp::Publisher<visualization_msgs::msg::Marker>::SharedPtr shapes_pub_;
    rclcpp::TimerBase::SharedPtr timer_;

    nav_msgs::msg::OccupancyGrid mapData_;
    visualization_msgs::msg::Marker points_, line_;
    std::vector<geometry_msgs::msg::Point> clicked_points_;
    std::vector<std::vector<float>> tree_;
    MTRand random_gen_;

    double eta_ = 2.0;
    double status_log_interval_ = 2.0;
    float init_map_x_ = 0.0f;
    float init_map_y_ = 0.0f;
    float x_start_x_ = 0.0f;
    float x_start_y_ = 0.0f;
    bool initialized_ = false;
    rclcpp::Time last_status_log_{0, 0, RCL_ROS_TIME};
    size_t free_count_ = 0;
    size_t frontier_count_ = 0;
    size_t obstacle_count_ = 0;
};

int main(int argc, char** argv)
{
    rclcpp::init(argc, argv);
    auto node = std::make_shared<GlobalRRTDetector>();
    node->run();
    rclcpp::shutdown();
    return 0;
}
