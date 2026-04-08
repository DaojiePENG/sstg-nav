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

        // Only need 1 clicked point as seed
        RCLCPP_INFO(this->get_logger(), "Waiting for 1 clicked point (seed near robot)...");
        while (clicked_points_.size() < 1 && rclcpp::ok()) {
            points_.header.stamp = this->now();
            points_.points = clicked_points_;
            shapes_pub_->publish(points_);
            rclcpp::spin_some(this->get_node_base_interface());
            rclcpp::sleep_for(std::chrono::milliseconds(50));
        }

        initializeFromMap();
        points_.points.clear();
        points_.header.stamp = this->now();
        shapes_pub_->publish(points_);

        initialized_ = true;
        last_status_log_ = this->now();
        timer_ = this->create_wall_timer(
            std::chrono::milliseconds(30),
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

    // Derive search area from current map extent — no manual corners needed
    void updateSearchAreaFromMap()
    {
        if (mapData_.data.empty()) return;

        float ox = mapData_.info.origin.position.x;
        float oy = mapData_.info.origin.position.y;
        float rez = mapData_.info.resolution;
        float w = static_cast<float>(mapData_.info.width) * rez;
        float h = static_cast<float>(mapData_.info.height) * rez;

        const float margin = std::max(static_cast<float>(eta_ * 2.0), 1.0f);
        float min_x = ox - margin;
        float max_x = ox + w + margin;
        float min_y = oy - margin;
        float max_y = oy + h + margin;

        init_map_x_ = max_x - min_x;
        init_map_y_ = max_y - min_y;
        x_start_x_ = (min_x + max_x) * 0.5f;
        x_start_y_ = (min_y + max_y) * 0.5f;
    }

    void initializeFromMap()
    {
        const auto &seed = clicked_points_[0];

        updateSearchAreaFromMap();

        tree_.clear();
        tree_.push_back({static_cast<float>(seed.x), static_cast<float>(seed.y)});
        line_.points.clear();

        RCLCPP_INFO(
            this->get_logger(),
            "Global RRT initialized from map extent: area=%.1f x %.1f, seed=(%.2f, %.2f), eta=%.2f",
            init_map_x_, init_map_y_, seed.x, seed.y, eta_);
    }

    void mapCallback(const nav_msgs::msg::OccupancyGrid::SharedPtr msg)
    {
        mapData_ = *msg;
        // Auto-grow search area as SLAM expands the map
        if (initialized_) {
            updateSearchAreaFromMap();
        }
    }

    void clickedCallback(const geometry_msgs::msg::PointStamped::SharedPtr msg)
    {
        geometry_msgs::msg::Point p;
        p.x = msg->point.x;
        p.y = msg->point.y;
        p.z = msg->point.z;

        if (!initialized_) {
            if (clicked_points_.empty()) {
                clicked_points_.push_back(p);
            }
            return;
        }

        // After init, additional clicks plant seeds at free/unknown boundary
        plantBoundarySeed(p);
    }

    void plantBoundarySeed(const geometry_msgs::msg::Point &p)
    {
        if (mapData_.data.empty() || tree_.empty()) return;

        std::vector<float> clicked_pt = {static_cast<float>(p.x), static_cast<float>(p.y)};
        std::vector<float> nearest = Nearest(tree_, clicked_pt);
        float rez = mapData_.info.resolution;
        float dist = Norm(nearest, clicked_pt);
        int steps = std::min(static_cast<int>(dist / std::max(rez, 0.01f)), 500);
        std::vector<float> best_free = nearest;

        float dx = (clicked_pt[0] - nearest[0]);
        float dy = (clicked_pt[1] - nearest[1]);
        if (dist > 0.001f) { dx /= dist; dy /= dist; }

        float map_ox = mapData_.info.origin.position.x;
        float map_oy = mapData_.info.origin.position.y;
        int map_w = static_cast<int>(mapData_.info.width);
        int map_h = static_cast<int>(mapData_.info.height);

        for (int i = 1; i <= steps; ++i) {
            float wx = nearest[0] + dx * rez * i;
            float wy = nearest[1] + dy * rez * i;
            int gx = static_cast<int>(std::floor((wx - map_ox) / rez));
            int gy = static_cast<int>(std::floor((wy - map_oy) / rez));
            if (gx < 0 || gx >= map_w || gy < 0 || gy >= map_h) break;
            int idx = gy * map_w + gx;
            if (idx < 0 || idx >= static_cast<int>(mapData_.data.size())) break;
            if (mapData_.data[idx] == 0) {
                best_free = {wx, wy};
            } else {
                break;
            }
        }

        if (Norm(best_free, nearest) > rez * 2) {
            tree_.push_back(best_free);
            geometry_msgs::msg::Point p1, p2;
            p1.x = nearest[0]; p1.y = nearest[1]; p1.z = 0.0;
            p2.x = best_free[0]; p2.y = best_free[1]; p2.z = 0.0;
            line_.points.push_back(p1);
            line_.points.push_back(p2);
            RCLCPP_INFO(this->get_logger(),
                "Seed planted at boundary (%.2f, %.2f), tree=%zu",
                best_free[0], best_free[1], tree_.size());
        } else {
            RCLCPP_INFO(this->get_logger(),
                "Clicked (%.2f, %.2f) — no free boundary found along path", p.x, p.y);
        }
    }

    void publishStatusIfDue()
    {
        const auto now = this->now();
        if ((now - last_status_log_).seconds() < status_log_interval_) {
            return;
        }

        RCLCPP_INFO(
            this->get_logger(),
            "Global RRT stats: tree_nodes=%zu edges=%zu free=%zu frontier=%zu blocked=%zu area=%.0fx%.0f",
            tree_.size(), line_.points.size() / 2, free_count_, frontier_count_, obstacle_count_,
            init_map_x_, init_map_y_);

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

        const int batch = 30;
        for (int b = 0; b < batch; ++b) {

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

        } // end batch loop

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
