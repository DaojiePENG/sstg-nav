#include "rclcpp/rclcpp.hpp"
#include "nav_msgs/msg/occupancy_grid.hpp"
#include "geometry_msgs/msg/point_stamped.hpp"
#include "visualization_msgs/msg/marker.hpp"
#include "tf2_ros/transform_listener.h"
#include "tf2_ros/buffer.h"
#include "functions.h"
#include "mtrand.h"
#include <vector>
#include <algorithm>

class LocalRRTDetector : public rclcpp::Node
{
public:
    LocalRRTDetector() : Node("local_rrt_detector")
    {
        this->declare_parameter("eta", 0.5);
        this->declare_parameter("map_topic", "/map");
        this->declare_parameter("range", 5.0);
        this->declare_parameter("robot_frame", "base_link");
        this->declare_parameter("max_tree_nodes", 500);
        this->declare_parameter("status_log_interval", 2.0);

        eta_ = this->get_parameter("eta").as_double();
        range_ = this->get_parameter("range").as_double();
        robot_frame_ = this->get_parameter("robot_frame").as_string();
        max_tree_nodes_ = this->get_parameter("max_tree_nodes").as_int();
        status_log_interval_ = this->get_parameter("status_log_interval").as_double();
        reset_distance_ = std::max(eta_ * 4.0, 0.75);
        std::string map_topic = this->get_parameter("map_topic").as_string();
        auto map_qos = rclcpp::QoS(rclcpp::KeepLast(1)).reliable().transient_local();

        map_sub_ = this->create_subscription<nav_msgs::msg::OccupancyGrid>(
            map_topic, map_qos, std::bind(&LocalRRTDetector::mapCallback, this, std::placeholders::_1));

        clicked_sub_ = this->create_subscription<geometry_msgs::msg::PointStamped>(
            "/clicked_point", 10, std::bind(&LocalRRTDetector::clickedCallback, this, std::placeholders::_1));

        targets_pub_ = this->create_publisher<geometry_msgs::msg::PointStamped>("/detected_points", 10);
        shapes_pub_ = this->create_publisher<visualization_msgs::msg::Marker>("shapes", 10);

        tf_buffer_ = std::make_shared<tf2_ros::Buffer>(this->get_clock());
        tf_listener_ = std::make_shared<tf2_ros::TransformListener>(*tf_buffer_);

        RCLCPP_INFO(this->get_logger(), "Local RRT detector initialized");
    }

    void run()
    {
        while (mapData_.data.empty() && rclcpp::ok()) {
            rclcpp::spin_some(this->get_node_base_interface());
            rclcpp::sleep_for(std::chrono::milliseconds(100));
        }

        initMarkers();

        // Only need 1 clicked point as seed
        RCLCPP_INFO(this->get_logger(), "Local RRT waiting for 1 clicked point...");
        while (clicked_points_.size() < 1 && rclcpp::ok()) {
            points_.header.stamp = this->now();
            points_.points = clicked_points_;
            shapes_pub_->publish(points_);
            rclcpp::spin_some(this->get_node_base_interface());
            rclcpp::sleep_for(std::chrono::milliseconds(50));
        }

        initializeFromMap();
        if (updateRobotPose()) {
            resetTree(robot_x_, robot_y_);
        } else {
            resetTree(clicked_points_[0].x, clicked_points_[0].y);
        }

        points_.points.clear();
        points_.header.stamp = this->now();
        shapes_pub_->publish(points_);

        initialized_ = true;
        last_status_log_ = this->now();
        timer_ = this->create_wall_timer(
            std::chrono::milliseconds(50),
            std::bind(&LocalRRTDetector::rrtLoop, this));

        rclcpp::spin(this->shared_from_this());
    }

private:
    void initMarkers()
    {
        points_.header.frame_id = mapData_.header.frame_id;
        line_.header.frame_id = mapData_.header.frame_id;

        points_.ns = "local_rrt_points";
        line_.ns = "local_rrt_tree";
        points_.id = 10;
        line_.id = 11;

        points_.type = visualization_msgs::msg::Marker::POINTS;
        line_.type = visualization_msgs::msg::Marker::LINE_LIST;
        points_.action = visualization_msgs::msg::Marker::ADD;
        line_.action = visualization_msgs::msg::Marker::ADD;
        points_.pose.orientation.w = 1.0;
        line_.pose.orientation.w = 1.0;
        line_.scale.x = 0.025;
        line_.scale.y = 0.025;
        points_.scale.x = 0.18;
        points_.scale.y = 0.18;

        line_.color.r = 1.0;
        line_.color.g = 90.0 / 255.0;
        line_.color.b = 0.0;
        line_.color.a = 1.0;

        points_.color.r = 1.0;
        points_.color.g = 0.6;
        points_.color.b = 0.0;
        points_.color.a = 1.0;
    }

    // Derive search area from current map extent — auto-grow with SLAM
    void updateSearchAreaFromMap()
    {
        if (mapData_.data.empty()) return;

        float ox = mapData_.info.origin.position.x;
        float oy = mapData_.info.origin.position.y;
        float rez = mapData_.info.resolution;
        float w = static_cast<float>(mapData_.info.width) * rez;
        float h = static_cast<float>(mapData_.info.height) * rez;

        const double margin = std::max(eta_ * 2.0, 1.0);
        min_x_ = static_cast<double>(ox) - margin;
        max_x_ = static_cast<double>(ox + w) + margin;
        min_y_ = static_cast<double>(oy) - margin;
        max_y_ = static_cast<double>(oy + h) + margin;
    }

    void initializeFromMap()
    {
        updateSearchAreaFromMap();

        RCLCPP_INFO(
            this->get_logger(),
            "Local RRT initialized from map extent: bbox=[%.2f,%.2f]x[%.2f,%.2f], eta=%.2f, range=%.2f",
            min_x_, max_x_, min_y_, max_y_, eta_, range_);
    }

    bool updateRobotPose()
    {
        try {
            auto transform = tf_buffer_->lookupTransform(
                mapData_.header.frame_id, robot_frame_, tf2::TimePointZero);
            robot_x_ = transform.transform.translation.x;
            robot_y_ = transform.transform.translation.y;
            return true;
        } catch (const tf2::TransformException &) {
            return false;
        }
    }

    void resetTree(double root_x, double root_y)
    {
        tree_.clear();
        tree_.push_back({static_cast<float>(root_x), static_cast<float>(root_y)});
        root_x_ = root_x;
        root_y_ = root_y;
        line_.points.clear();
        line_.header.stamp = this->now();
        shapes_pub_->publish(line_);
    }

    void publishStatusIfDue()
    {
        const auto now = this->now();
        if ((now - last_status_log_).seconds() < status_log_interval_) {
            return;
        }

        RCLCPP_INFO(
            this->get_logger(),
            "Local RRT stats: tree_nodes=%zu edges=%zu free=%zu frontier=%zu blocked=%zu root=(%.2f, %.2f) robot=(%.2f, %.2f)",
            tree_.size(), line_.points.size() / 2, free_count_, frontier_count_, obstacle_count_, root_x_, root_y_, robot_x_, robot_y_);

        free_count_ = 0;
        frontier_count_ = 0;
        obstacle_count_ = 0;
        last_status_log_ = now;
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
        // After init, additional clicks are ignored (area auto-grows with map)
    }

    void rrtLoop()
    {
        if (!initialized_ || mapData_.data.empty()) {
            return;
        }

        if (!updateRobotPose()) {
            return;
        }

        if (tree_.empty() || Norm({static_cast<float>(root_x_), static_cast<float>(root_y_)}, {static_cast<float>(robot_x_), static_cast<float>(robot_y_)}) > reset_distance_) {
            resetTree(robot_x_, robot_y_);
        }

        if (static_cast<int>(tree_.size()) >= max_tree_nodes_) {
            resetTree(robot_x_, robot_y_);
        }

        std::vector<float> x_rand, x_nearest, x_new;

        const int batch = 8;
        for (int b = 0; b < batch; ++b) {
        x_rand.clear(); x_nearest.clear(); x_new.clear();

        float xr = static_cast<float>((random_gen_() * range_ * 2.0) - range_ + robot_x_);
        float yr = static_cast<float>((random_gen_() * range_ * 2.0) - range_ + robot_y_);
        xr = std::max(static_cast<float>(min_x_), std::min(static_cast<float>(max_x_), xr));
        yr = std::max(static_cast<float>(min_y_), std::min(static_cast<float>(max_y_), yr));
        x_rand.push_back(xr);
        x_rand.push_back(yr);

        x_nearest = Nearest(tree_, x_rand);
        x_new = Steer(x_nearest, x_rand, eta_);

        int checking = ObstacleFree(x_nearest, x_new, mapData_);

        if (checking == -1) {
            ++frontier_count_;

            geometry_msgs::msg::PointStamped goal;
            goal.header.stamp = this->now();
            goal.header.frame_id = mapData_.header.frame_id;
            goal.point.x = x_new[0];
            goal.point.y = x_new[1];
            goal.point.z = 0.0;
            targets_pub_->publish(goal);

            geometry_msgs::msg::Point p;
            p.x = x_new[0];
            p.y = x_new[1];
            p.z = 0.0;
            points_.points.clear();
            points_.points.push_back(p);
            points_.header.stamp = this->now();
            shapes_pub_->publish(points_);

            resetTree(robot_x_, robot_y_);
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

        if (checking == -1) break;

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
    std::shared_ptr<tf2_ros::Buffer> tf_buffer_;
    std::shared_ptr<tf2_ros::TransformListener> tf_listener_;

    nav_msgs::msg::OccupancyGrid mapData_;
    visualization_msgs::msg::Marker points_, line_;
    std::vector<geometry_msgs::msg::Point> clicked_points_;
    std::vector<std::vector<float>> tree_;
    MTRand random_gen_;

    double eta_ = 0.5;
    double range_ = 5.0;
    double reset_distance_ = 0.75;
    int max_tree_nodes_ = 250;
    double status_log_interval_ = 2.0;
    std::string robot_frame_;
    double robot_x_ = 0.0;
    double robot_y_ = 0.0;
    double root_x_ = 0.0;
    double root_y_ = 0.0;
    double min_x_ = 0.0;
    double max_x_ = 0.0;
    double min_y_ = 0.0;
    double max_y_ = 0.0;
    bool initialized_ = false;
    rclcpp::Time last_status_log_{0, 0, RCL_ROS_TIME};
    size_t free_count_ = 0;
    size_t frontier_count_ = 0;
    size_t obstacle_count_ = 0;
};

int main(int argc, char** argv)
{
    rclcpp::init(argc, argv);
    auto node = std::make_shared<LocalRRTDetector>();
    node->run();
    rclcpp::shutdown();
    return 0;
}
