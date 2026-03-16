
Terraform used the selected providers to generate the following execution
plan. Resource actions are indicated with the following symbols:
  [32m+[0m create[0m

Terraform will perform the following actions:

[1m  # module.alb.aws_lb.main[0m will be created
[0m  [32m+[0m[0m resource "aws_lb" "main" {
      [32m+[0m[0m arn                                                          = (known after apply)
      [32m+[0m[0m arn_suffix                                                   = (known after apply)
      [32m+[0m[0m client_keep_alive                                            = 3600
      [32m+[0m[0m desync_mitigation_mode                                       = "defensive"
      [32m+[0m[0m dns_name                                                     = (known after apply)
      [32m+[0m[0m drop_invalid_header_fields                                   = false
      [32m+[0m[0m enable_deletion_protection                                   = false
      [32m+[0m[0m enable_http2                                                 = true
      [32m+[0m[0m enable_tls_version_and_cipher_suite_headers                  = false
      [32m+[0m[0m enable_waf_fail_open                                         = false
      [32m+[0m[0m enable_xff_client_port                                       = false
      [32m+[0m[0m enable_zonal_shift                                           = false
      [32m+[0m[0m enforce_security_group_inbound_rules_on_private_link_traffic = (known after apply)
      [32m+[0m[0m id                                                           = (known after apply)
      [32m+[0m[0m idle_timeout                                                 = 300
      [32m+[0m[0m internal                                                     = false
      [32m+[0m[0m ip_address_type                                              = (known after apply)
      [32m+[0m[0m load_balancer_type                                           = "application"
      [32m+[0m[0m name                                                         = "freebird-dev-alb"
      [32m+[0m[0m name_prefix                                                  = (known after apply)
      [32m+[0m[0m preserve_host_header                                         = false
      [32m+[0m[0m security_groups                                              = (known after apply)
      [32m+[0m[0m subnets                                                      = (known after apply)
      [32m+[0m[0m tags                                                         = {
          [32m+[0m[0m "Name" = "freebird-dev-alb"
        }
      [32m+[0m[0m tags_all                                                     = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-alb"
          [32m+[0m[0m "Project"     = "freebird"
        }
      [32m+[0m[0m vpc_id                                                       = (known after apply)
      [32m+[0m[0m xff_header_processing_mode                                   = "append"
      [32m+[0m[0m zone_id                                                      = (known after apply)

      [32m+[0m[0m subnet_mapping (known after apply)
    }

[1m  # module.alb.aws_lb_listener.http[0m will be created
[0m  [32m+[0m[0m resource "aws_lb_listener" "http" {
      [32m+[0m[0m arn                                                                   = (known after apply)
      [32m+[0m[0m id                                                                    = (known after apply)
      [32m+[0m[0m load_balancer_arn                                                     = (known after apply)
      [32m+[0m[0m port                                                                  = 80
      [32m+[0m[0m protocol                                                              = "HTTP"
      [32m+[0m[0m routing_http_request_x_amzn_mtls_clientcert_header_name               = (known after apply)
      [32m+[0m[0m routing_http_request_x_amzn_mtls_clientcert_issuer_header_name        = (known after apply)
      [32m+[0m[0m routing_http_request_x_amzn_mtls_clientcert_leaf_header_name          = (known after apply)
      [32m+[0m[0m routing_http_request_x_amzn_mtls_clientcert_serial_number_header_name = (known after apply)
      [32m+[0m[0m routing_http_request_x_amzn_mtls_clientcert_subject_header_name       = (known after apply)
      [32m+[0m[0m routing_http_request_x_amzn_mtls_clientcert_validity_header_name      = (known after apply)
      [32m+[0m[0m routing_http_request_x_amzn_tls_cipher_suite_header_name              = (known after apply)
      [32m+[0m[0m routing_http_request_x_amzn_tls_version_header_name                   = (known after apply)
      [32m+[0m[0m routing_http_response_access_control_allow_credentials_header_value   = (known after apply)
      [32m+[0m[0m routing_http_response_access_control_allow_headers_header_value       = (known after apply)
      [32m+[0m[0m routing_http_response_access_control_allow_methods_header_value       = (known after apply)
      [32m+[0m[0m routing_http_response_access_control_allow_origin_header_value        = (known after apply)
      [32m+[0m[0m routing_http_response_access_control_expose_headers_header_value      = (known after apply)
      [32m+[0m[0m routing_http_response_access_control_max_age_header_value             = (known after apply)
      [32m+[0m[0m routing_http_response_content_security_policy_header_value            = (known after apply)
      [32m+[0m[0m routing_http_response_server_enabled                                  = (known after apply)
      [32m+[0m[0m routing_http_response_strict_transport_security_header_value          = (known after apply)
      [32m+[0m[0m routing_http_response_x_content_type_options_header_value             = (known after apply)
      [32m+[0m[0m routing_http_response_x_frame_options_header_value                    = (known after apply)
      [32m+[0m[0m ssl_policy                                                            = (known after apply)
      [32m+[0m[0m tags_all                                                              = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Project"     = "freebird"
        }
      [32m+[0m[0m tcp_idle_timeout_seconds                                              = (known after apply)

      [32m+[0m[0m default_action {
          [32m+[0m[0m order = (known after apply)
          [32m+[0m[0m type  = "redirect"

          [32m+[0m[0m redirect {
              [32m+[0m[0m host        = "#{host}"
              [32m+[0m[0m path        = "/#{path}"
              [32m+[0m[0m port        = "443"
              [32m+[0m[0m protocol    = "HTTPS"
              [32m+[0m[0m query       = "#{query}"
              [32m+[0m[0m status_code = "HTTP_301"
            }
        }

      [32m+[0m[0m mutual_authentication (known after apply)
    }

[1m  # module.alb.aws_lb_target_group.main[0m will be created
[0m  [32m+[0m[0m resource "aws_lb_target_group" "main" {
      [32m+[0m[0m arn                                = (known after apply)
      [32m+[0m[0m arn_suffix                         = (known after apply)
      [32m+[0m[0m connection_termination             = (known after apply)
      [32m+[0m[0m deregistration_delay               = "300"
      [32m+[0m[0m id                                 = (known after apply)
      [32m+[0m[0m ip_address_type                    = (known after apply)
      [32m+[0m[0m lambda_multi_value_headers_enabled = false
      [32m+[0m[0m load_balancer_arns                 = (known after apply)
      [32m+[0m[0m load_balancing_algorithm_type      = (known after apply)
      [32m+[0m[0m load_balancing_anomaly_mitigation  = (known after apply)
      [32m+[0m[0m load_balancing_cross_zone_enabled  = (known after apply)
      [32m+[0m[0m name                               = "freebird-dev-tg"
      [32m+[0m[0m name_prefix                        = (known after apply)
      [32m+[0m[0m port                               = 8000
      [32m+[0m[0m preserve_client_ip                 = (known after apply)
      [32m+[0m[0m protocol                           = "HTTP"
      [32m+[0m[0m protocol_version                   = (known after apply)
      [32m+[0m[0m proxy_protocol_v2                  = false
      [32m+[0m[0m slow_start                         = 0
      [32m+[0m[0m tags                               = {
          [32m+[0m[0m "Name" = "freebird-dev-tg"
        }
      [32m+[0m[0m tags_all                           = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-tg"
          [32m+[0m[0m "Project"     = "freebird"
        }
      [32m+[0m[0m target_type                        = "instance"
      [32m+[0m[0m vpc_id                             = (known after apply)

      [32m+[0m[0m health_check {
          [32m+[0m[0m enabled             = true
          [32m+[0m[0m healthy_threshold   = 2
          [32m+[0m[0m interval            = 30
          [32m+[0m[0m matcher             = "200"
          [32m+[0m[0m path                = "/health"
          [32m+[0m[0m port                = "traffic-port"
          [32m+[0m[0m protocol            = "HTTP"
          [32m+[0m[0m timeout             = 10
          [32m+[0m[0m unhealthy_threshold = 3
        }

      [32m+[0m[0m stickiness {
          [32m+[0m[0m cookie_duration = 3600
          [32m+[0m[0m enabled         = true
          [32m+[0m[0m type            = "lb_cookie"
        }

      [32m+[0m[0m target_failover (known after apply)

      [32m+[0m[0m target_group_health (known after apply)

      [32m+[0m[0m target_health_state (known after apply)
    }

[1m  # module.alb.aws_security_group.alb[0m will be created
[0m  [32m+[0m[0m resource "aws_security_group" "alb" {
      [32m+[0m[0m arn                    = (known after apply)
      [32m+[0m[0m description            = "Security group for ALB"
      [32m+[0m[0m egress                 = [
          [32m+[0m[0m {
              [32m+[0m[0m cidr_blocks      = [
                  [32m+[0m[0m "0.0.0.0/0",
                ]
              [32m+[0m[0m description      = "Allow all outbound"
              [32m+[0m[0m from_port        = 0
              [32m+[0m[0m ipv6_cidr_blocks = []
              [32m+[0m[0m prefix_list_ids  = []
              [32m+[0m[0m protocol         = "-1"
              [32m+[0m[0m security_groups  = []
              [32m+[0m[0m self             = false
              [32m+[0m[0m to_port          = 0
            },
        ]
      [32m+[0m[0m id                     = (known after apply)
      [32m+[0m[0m ingress                = [
          [32m+[0m[0m {
              [32m+[0m[0m cidr_blocks      = [
                  [32m+[0m[0m "0.0.0.0/0",
                ]
              [32m+[0m[0m description      = "HTTP from anywhere (redirect to HTTPS)"
              [32m+[0m[0m from_port        = 80
              [32m+[0m[0m ipv6_cidr_blocks = []
              [32m+[0m[0m prefix_list_ids  = []
              [32m+[0m[0m protocol         = "tcp"
              [32m+[0m[0m security_groups  = []
              [32m+[0m[0m self             = false
              [32m+[0m[0m to_port          = 80
            },
          [32m+[0m[0m {
              [32m+[0m[0m cidr_blocks      = [
                  [32m+[0m[0m "0.0.0.0/0",
                ]
              [32m+[0m[0m description      = "HTTPS from anywhere"
              [32m+[0m[0m from_port        = 443
              [32m+[0m[0m ipv6_cidr_blocks = []
              [32m+[0m[0m prefix_list_ids  = []
              [32m+[0m[0m protocol         = "tcp"
              [32m+[0m[0m security_groups  = []
              [32m+[0m[0m self             = false
              [32m+[0m[0m to_port          = 443
            },
        ]
      [32m+[0m[0m name                   = "freebird-dev-alb-sg"
      [32m+[0m[0m name_prefix            = (known after apply)
      [32m+[0m[0m owner_id               = (known after apply)
      [32m+[0m[0m revoke_rules_on_delete = false
      [32m+[0m[0m tags                   = {
          [32m+[0m[0m "Name" = "freebird-dev-alb-sg"
        }
      [32m+[0m[0m tags_all               = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-alb-sg"
          [32m+[0m[0m "Project"     = "freebird"
        }
      [32m+[0m[0m vpc_id                 = (known after apply)
    }

[1m  # module.ec2.aws_autoscaling_group.main[0m will be created
[0m  [32m+[0m[0m resource "aws_autoscaling_group" "main" {
      [32m+[0m[0m arn                              = (known after apply)
      [32m+[0m[0m availability_zones               = (known after apply)
      [32m+[0m[0m default_cooldown                 = (known after apply)
      [32m+[0m[0m desired_capacity                 = 1
      [32m+[0m[0m force_delete                     = false
      [32m+[0m[0m force_delete_warm_pool           = false
      [32m+[0m[0m health_check_grace_period        = 300
      [32m+[0m[0m health_check_type                = "ELB"
      [32m+[0m[0m id                               = (known after apply)
      [32m+[0m[0m ignore_failed_scaling_activities = false
      [32m+[0m[0m load_balancers                   = (known after apply)
      [32m+[0m[0m max_size                         = 2
      [32m+[0m[0m metrics_granularity              = "1Minute"
      [32m+[0m[0m min_size                         = 1
      [32m+[0m[0m name                             = "freebird-dev-asg"
      [32m+[0m[0m name_prefix                      = (known after apply)
      [32m+[0m[0m predicted_capacity               = (known after apply)
      [32m+[0m[0m protect_from_scale_in            = false
      [32m+[0m[0m service_linked_role_arn          = (known after apply)
      [32m+[0m[0m target_group_arns                = (known after apply)
      [32m+[0m[0m vpc_zone_identifier              = (known after apply)
      [32m+[0m[0m wait_for_capacity_timeout        = "10m"
      [32m+[0m[0m warm_pool_size                   = (known after apply)

      [32m+[0m[0m availability_zone_distribution (known after apply)

      [32m+[0m[0m capacity_reservation_specification (known after apply)

      [32m+[0m[0m instance_refresh {
          [32m+[0m[0m strategy = "Rolling"

          [32m+[0m[0m preferences {
              [32m+[0m[0m max_healthy_percentage       = 100
              [32m+[0m[0m min_healthy_percentage       = 50
              [32m+[0m[0m scale_in_protected_instances = "Ignore"
              [32m+[0m[0m skip_matching                = false
              [32m+[0m[0m standby_instances            = "Ignore"
            }
        }

      [32m+[0m[0m launch_template {
          [32m+[0m[0m id      = (known after apply)
          [32m+[0m[0m name    = (known after apply)
          [32m+[0m[0m version = "$Latest"
        }

      [32m+[0m[0m mixed_instances_policy (known after apply)

      [32m+[0m[0m tag {
          [32m+[0m[0m key                 = "Environment"
          [32m+[0m[0m propagate_at_launch = true
          [32m+[0m[0m value               = "dev"
        }
      [32m+[0m[0m tag {
          [32m+[0m[0m key                 = "Name"
          [32m+[0m[0m propagate_at_launch = true
          [32m+[0m[0m value               = "freebird-dev-instance"
        }
      [32m+[0m[0m tag {
          [32m+[0m[0m key                 = "Project"
          [32m+[0m[0m propagate_at_launch = true
          [32m+[0m[0m value               = "freebird"
        }

      [32m+[0m[0m traffic_source (known after apply)
    }

[1m  # module.ec2.aws_launch_template.main[0m will be created
[0m  [32m+[0m[0m resource "aws_launch_template" "main" {
      [32m+[0m[0m arn             = (known after apply)
      [32m+[0m[0m default_version = (known after apply)
      [32m+[0m[0m id              = (known after apply)
      [32m+[0m[0m image_id        = "ami-0771b6766e1e61632"
      [32m+[0m[0m instance_type   = "m5.xlarge"
      [32m+[0m[0m latest_version  = (known after apply)
      [32m+[0m[0m name            = (known after apply)
      [32m+[0m[0m name_prefix     = "freebird-dev-"
      [32m+[0m[0m tags_all        = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Project"     = "freebird"
        }
      [32m+[0m[0m user_data       = "IyEvYmluL2Jhc2gKIyA9PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PQojIEVDMiBVc2VyIERhdGEgU2NyaXB0IC0gRnJlZWJpcmQgQmFja2VuZCB3aXRoIE5pdHJvIEVuY2xhdmUKIyA9PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PQpzZXQgLWV1byBwaXBlZmFpbAoKIyBWYXJpYWJsZXMgZnJvbSBUZXJyYWZvcm0KUFJPSkVDVD0iZnJlZWJpcmQiCkVOVklST05NRU5UPSJkZXYiClNFQ1JFVFNfQVJOX1BSRUZJWD0iYXJuOmF3czpzZWNyZXRzbWFuYWdlcjp1cy1lYXN0LTE6ODc3MzUyNzk5MjcyOnNlY3JldDpmcmVlYmlyZC9kZXYvIgpGUk9OVEVORF9VUkw9Imh0dHA6Ly9sb2NhbGhvc3Q6MzAwMCIKCiMgTG9nZ2luZwpleGVjID4gPih0ZWUgL3Zhci9sb2cvdXNlci1kYXRhLmxvZ3xsb2dnZXIgLXQgdXNlci1kYXRhIC1zIDI+L2Rldi9jb25zb2xlKSAyPiYxCmVjaG8gIlN0YXJ0aW5nIEZyZWViaXJkIGJhY2tlbmQgc2V0dXAuLi4iCgojIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCiMgSW5zdGFsbCBkZXBlbmRlbmNpZXMKIyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQp5dW0gdXBkYXRlIC15CmFtYXpvbi1saW51eC1leHRyYXMgaW5zdGFsbCBkb2NrZXIgLXkKeXVtIGluc3RhbGwgLXkgYXdzLWNsaSBqcQoKIyBTdGFydCBEb2NrZXIKc3lzdGVtY3RsIHN0YXJ0IGRvY2tlcgpzeXN0ZW1jdGwgZW5hYmxlIGRvY2tlcgoKIyBJbnN0YWxsIE5pdHJvIENMSQphbWF6b24tbGludXgtZXh0cmFzIGluc3RhbGwgYXdzLW5pdHJvLWVuY2xhdmVzLWNsaSAteQp5dW0gaW5zdGFsbCAteSBhd3Mtbml0cm8tZW5jbGF2ZXMtY2xpLWRldmVsCgojIENvbmZpZ3VyZSBlbmNsYXZlIGFsbG9jYXRvcgpjYXQgPiAvZXRjL25pdHJvX2VuY2xhdmVzL2FsbG9jYXRvci55YW1sIDw8ICdFT0YnCi0tLQojIDJHQiBtZW1vcnkgZm9yIGVuY2xhdmUgKGFkanVzdCBiYXNlZCBvbiBtb2RlbCByZXF1aXJlbWVudHMpCm1lbW9yeV9taWI6IDIwNDgKIyAyIENQVXMgZm9yIGVuY2xhdmUKY3B1X2NvdW50OiAyCkVPRgoKIyBTdGFydCBOaXRybyBFbmNsYXZlIGFsbG9jYXRvcgpzeXN0ZW1jdGwgc3RhcnQgbml0cm8tZW5jbGF2ZXMtYWxsb2NhdG9yCnN5c3RlbWN0bCBlbmFibGUgbml0cm8tZW5jbGF2ZXMtYWxsb2NhdG9yCgojIEFkZCBlYzItdXNlciB0byBkb2NrZXIgYW5kIG5lIGdyb3Vwcwp1c2VybW9kIC1hRyBkb2NrZXIgZWMyLXVzZXIKdXNlcm1vZCAtYUcgbmUgZWMyLXVzZXIKCiMgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0KIyBGZXRjaCBzZWNyZXRzIGZyb20gU2VjcmV0cyBNYW5hZ2VyCiMgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0KZWNobyAiRmV0Y2hpbmcgc2VjcmV0cy4uLiIKCiMgR2V0IHRoZSBBV1MgcmVnaW9uClJFR0lPTj0kKGN1cmwgLXMgaHR0cDovLzE2OS4yNTQuMTY5LjI1NC9sYXRlc3QvbWV0YS1kYXRhL3BsYWNlbWVudC9yZWdpb24pCgojIEZldGNoIHNlY3JldHMKREFUQUJBU0VfVVJMPSQoYXdzIHNlY3JldHNtYW5hZ2VyIGdldC1zZWNyZXQtdmFsdWUgXAogICAgLS1yZWdpb24gIiRSRUdJT04iIFwKICAgIC0tc2VjcmV0LWlkICIke1NFQ1JFVFNfQVJOX1BSRUZJWH1kYXRhYmFzZV91cmwiIFwKICAgIC0tcXVlcnkgJ1NlY3JldFN0cmluZycgLS1vdXRwdXQgdGV4dCkKCkhVR0dJTkdGQUNFX1RPS0VOPSQoYXdzIHNlY3JldHNtYW5hZ2VyIGdldC1zZWNyZXQtdmFsdWUgXAogICAgLS1yZWdpb24gIiRSRUdJT04iIFwKICAgIC0tc2VjcmV0LWlkICIke1NFQ1JFVFNfQVJOX1BSRUZJWH1odWdnaW5nZmFjZV90b2tlbiIgXAogICAgLS1xdWVyeSAnU2VjcmV0U3RyaW5nJyAtLW91dHB1dCB0ZXh0KQoKQ0xFUktfSVNTVUVSPSQoYXdzIHNlY3JldHNtYW5hZ2VyIGdldC1zZWNyZXQtdmFsdWUgXAogICAgLS1yZWdpb24gIiRSRUdJT04iIFwKICAgIC0tc2VjcmV0LWlkICIke1NFQ1JFVFNfQVJOX1BSRUZJWH1jbGVya19pc3N1ZXIiIFwKICAgIC0tcXVlcnkgJ1NlY3JldFN0cmluZycgLS1vdXRwdXQgdGV4dCkKCkNMRVJLX1dFQkhPT0tfU0VDUkVUPSQoYXdzIHNlY3JldHNtYW5hZ2VyIGdldC1zZWNyZXQtdmFsdWUgXAogICAgLS1yZWdpb24gIiRSRUdJT04iIFwKICAgIC0tc2VjcmV0LWlkICIke1NFQ1JFVFNfQVJOX1BSRUZJWH1jbGVya193ZWJob29rX3NlY3JldCIgXAogICAgLS1xdWVyeSAnU2VjcmV0U3RyaW5nJyAtLW91dHB1dCB0ZXh0KQoKIyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQojIENyZWF0ZSBlbnZpcm9ubWVudCBmaWxlCiMgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0KY2F0ID4gL2hvbWUvZWMyLXVzZXIvLmVudiA8PCBFT0YKREFUQUJBU0VfVVJMPSREQVRBQkFTRV9VUkwKSFVHR0lOR0ZBQ0VfVE9LRU49JEhVR0dJTkdGQUNFX1RPS0VOCkNMRVJLX0lTU1VFUj0kQ0xFUktfSVNTVUVSCkNMRVJLX1dFQkhPT0tfU0VDUkVUPSRDTEVSS19XRUJIT09LX1NFQ1JFVApDT1JTX09SSUdJTlM9JEZST05URU5EX1VSTApERUJVRz1mYWxzZQpFTkNMQVZFX01PREU9bW9jawpFT0YKCmNobW9kIDYwMCAvaG9tZS9lYzItdXNlci8uZW52CmNob3duIGVjMi11c2VyOmVjMi11c2VyIC9ob21lL2VjMi11c2VyLy5lbnYKCiMgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0KIyBMb2dpbiB0byBFQ1IgYW5kIHB1bGwgaW1hZ2UKIyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQplY2hvICJQdWxsaW5nIGNvbnRhaW5lciBpbWFnZS4uLiIKQVdTX0FDQ09VTlRfSUQ9JChhd3Mgc3RzIGdldC1jYWxsZXItaWRlbnRpdHkgLS1xdWVyeSBBY2NvdW50IC0tb3V0cHV0IHRleHQpCkVDUl9SRVBPPSIkQVdTX0FDQ09VTlRfSUQuZGtyLmVjci4kUkVHSU9OLmFtYXpvbmF3cy5jb20vJFBST0pFQ1QtYmFja2VuZCIKCmF3cyBlY3IgZ2V0LWxvZ2luLXBhc3N3b3JkIC0tcmVnaW9uICIkUkVHSU9OIiB8IGRvY2tlciBsb2dpbiAtLXVzZXJuYW1lIEFXUyAtLXBhc3N3b3JkLXN0ZGluICIkRUNSX1JFUE8iCmRvY2tlciBwdWxsICIkRUNSX1JFUE86bGF0ZXN0IiB8fCBkb2NrZXIgcHVsbCAiJEVDUl9SRVBPOiRFTlZJUk9OTUVOVCIgfHwgdHJ1ZQoKIyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQojIFN0YXJ0IHRoZSBhcHBsaWNhdGlvbgojIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCmVjaG8gIlN0YXJ0aW5nIGFwcGxpY2F0aW9uLi4uIgoKIyBDcmVhdGUgc3lzdGVtZCBzZXJ2aWNlCmNhdCA+IC9ldGMvc3lzdGVtZC9zeXN0ZW0vZnJlZWJpcmQuc2VydmljZSA8PCBFT0YKW1VuaXRdCkRlc2NyaXB0aW9uPUZyZWViaXJkIEJhY2tlbmQKQWZ0ZXI9ZG9ja2VyLnNlcnZpY2UKUmVxdWlyZXM9ZG9ja2VyLnNlcnZpY2UKCltTZXJ2aWNlXQpUeXBlPXNpbXBsZQpSZXN0YXJ0PWFsd2F5cwpSZXN0YXJ0U2VjPTUKRXhlY1N0YXJ0PS91c3IvYmluL2RvY2tlciBydW4gLS1ybSBcCiAgICAtLW5hbWUgZnJlZWJpcmQgXAogICAgLS1lbnYtZmlsZSAvaG9tZS9lYzItdXNlci8uZW52IFwKICAgIC1wIDgwMDA6ODAwMCBcCiAgICAkRUNSX1JFUE86bGF0ZXN0CgpbSW5zdGFsbF0KV2FudGVkQnk9bXVsdGktdXNlci50YXJnZXQKRU9GCgojIFJlbG9hZCBhbmQgc3RhcnQgc2VydmljZQpzeXN0ZW1jdGwgZGFlbW9uLXJlbG9hZApzeXN0ZW1jdGwgZW5hYmxlIGZyZWViaXJkCnN5c3RlbWN0bCBzdGFydCBmcmVlYmlyZAoKZWNobyAiRnJlZWJpcmQgYmFja2VuZCBzZXR1cCBjb21wbGV0ZSEiCg=="

      [32m+[0m[0m block_device_mappings {
          [32m+[0m[0m device_name = "/dev/xvda"

          [32m+[0m[0m ebs {
              [32m+[0m[0m delete_on_termination      = "true"
              [32m+[0m[0m encrypted                  = "true"
              [32m+[0m[0m iops                       = (known after apply)
              [32m+[0m[0m throughput                 = (known after apply)
              [32m+[0m[0m volume_initialization_rate = (known after apply)
              [32m+[0m[0m volume_size                = 30
              [32m+[0m[0m volume_type                = "gp3"
            }
        }

      [32m+[0m[0m enclave_options {
          [32m+[0m[0m enabled = true
        }

      [32m+[0m[0m iam_instance_profile {
          [32m+[0m[0m name = "freebird-dev-ec2-profile"
        }

      [32m+[0m[0m metadata_options {
          [32m+[0m[0m http_endpoint               = "enabled"
          [32m+[0m[0m http_protocol_ipv6          = (known after apply)
          [32m+[0m[0m http_put_response_hop_limit = 1
          [32m+[0m[0m http_tokens                 = "required"
          [32m+[0m[0m instance_metadata_tags      = (known after apply)
        }

      [32m+[0m[0m network_interfaces {
          [32m+[0m[0m associate_public_ip_address = "false"
          [32m+[0m[0m security_groups             = (known after apply)
        }

      [32m+[0m[0m tag_specifications {
          [32m+[0m[0m resource_type = "instance"
          [32m+[0m[0m tags          = {
              [32m+[0m[0m "Name"    = "freebird-dev-instance"
              [32m+[0m[0m "Project" = "freebird"
            }
        }
    }

[1m  # module.ec2.aws_security_group.ec2[0m will be created
[0m  [32m+[0m[0m resource "aws_security_group" "ec2" {
      [32m+[0m[0m arn                    = (known after apply)
      [32m+[0m[0m description            = "Security group for EC2 instances"
      [32m+[0m[0m egress                 = [
          [32m+[0m[0m {
              [32m+[0m[0m cidr_blocks      = [
                  [32m+[0m[0m "0.0.0.0/0",
                ]
              [32m+[0m[0m description      = "Allow all outbound"
              [32m+[0m[0m from_port        = 0
              [32m+[0m[0m ipv6_cidr_blocks = []
              [32m+[0m[0m prefix_list_ids  = []
              [32m+[0m[0m protocol         = "-1"
              [32m+[0m[0m security_groups  = []
              [32m+[0m[0m self             = false
              [32m+[0m[0m to_port          = 0
            },
        ]
      [32m+[0m[0m id                     = (known after apply)
      [32m+[0m[0m ingress                = [
          [32m+[0m[0m {
              [32m+[0m[0m cidr_blocks      = []
              [32m+[0m[0m description      = "HTTP from ALB"
              [32m+[0m[0m from_port        = 8000
              [32m+[0m[0m ipv6_cidr_blocks = []
              [32m+[0m[0m prefix_list_ids  = []
              [32m+[0m[0m protocol         = "tcp"
              [32m+[0m[0m security_groups  = (known after apply)
              [32m+[0m[0m self             = false
              [32m+[0m[0m to_port          = 8000
            },
        ]
      [32m+[0m[0m name                   = "freebird-dev-ec2-sg"
      [32m+[0m[0m name_prefix            = (known after apply)
      [32m+[0m[0m owner_id               = (known after apply)
      [32m+[0m[0m revoke_rules_on_delete = false
      [32m+[0m[0m tags                   = {
          [32m+[0m[0m "Name" = "freebird-dev-ec2-sg"
        }
      [32m+[0m[0m tags_all               = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-ec2-sg"
          [32m+[0m[0m "Project"     = "freebird"
        }
      [32m+[0m[0m vpc_id                 = (known after apply)
    }

[1m  # module.iam.aws_iam_instance_profile.ec2[0m will be created
[0m  [32m+[0m[0m resource "aws_iam_instance_profile" "ec2" {
      [32m+[0m[0m arn         = (known after apply)
      [32m+[0m[0m create_date = (known after apply)
      [32m+[0m[0m id          = (known after apply)
      [32m+[0m[0m name        = "freebird-dev-ec2-profile"
      [32m+[0m[0m name_prefix = (known after apply)
      [32m+[0m[0m path        = "/"
      [32m+[0m[0m role        = "freebird-dev-ec2-role"
      [32m+[0m[0m tags_all    = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Project"     = "freebird"
        }
      [32m+[0m[0m unique_id   = (known after apply)
    }

[1m  # module.iam.aws_iam_openid_connect_provider.github[0][0m will be created
[0m  [32m+[0m[0m resource "aws_iam_openid_connect_provider" "github" {
      [32m+[0m[0m arn             = (known after apply)
      [32m+[0m[0m client_id_list  = [
          [32m+[0m[0m "sts.amazonaws.com",
        ]
      [32m+[0m[0m id              = (known after apply)
      [32m+[0m[0m tags            = {
          [32m+[0m[0m "Name" = "freebird-github-oidc"
        }
      [32m+[0m[0m tags_all        = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-github-oidc"
          [32m+[0m[0m "Project"     = "freebird"
        }
      [32m+[0m[0m thumbprint_list = [
          [32m+[0m[0m "6938fd4d98bab03faadb97b34396831e3780aea1",
        ]
      [32m+[0m[0m url             = "https://token.actions.githubusercontent.com"
    }

[1m  # module.iam.aws_iam_role.ec2[0m will be created
[0m  [32m+[0m[0m resource "aws_iam_role" "ec2" {
      [32m+[0m[0m arn                   = (known after apply)
      [32m+[0m[0m assume_role_policy    = jsonencode(
            {
              [32m+[0m[0m Statement = [
                  [32m+[0m[0m {
                      [32m+[0m[0m Action    = "sts:AssumeRole"
                      [32m+[0m[0m Effect    = "Allow"
                      [32m+[0m[0m Principal = {
                          [32m+[0m[0m Service = "ec2.amazonaws.com"
                        }
                    },
                ]
              [32m+[0m[0m Version   = "2012-10-17"
            }
        )
      [32m+[0m[0m create_date           = (known after apply)
      [32m+[0m[0m force_detach_policies = false
      [32m+[0m[0m id                    = (known after apply)
      [32m+[0m[0m managed_policy_arns   = (known after apply)
      [32m+[0m[0m max_session_duration  = 3600
      [32m+[0m[0m name                  = "freebird-dev-ec2-role"
      [32m+[0m[0m name_prefix           = (known after apply)
      [32m+[0m[0m path                  = "/"
      [32m+[0m[0m tags                  = {
          [32m+[0m[0m "Name" = "freebird-dev-ec2-role"
        }
      [32m+[0m[0m tags_all              = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-ec2-role"
          [32m+[0m[0m "Project"     = "freebird"
        }
      [32m+[0m[0m unique_id             = (known after apply)

      [32m+[0m[0m inline_policy (known after apply)
    }

[1m  # module.iam.aws_iam_role.github_actions[0][0m will be created
[0m  [32m+[0m[0m resource "aws_iam_role" "github_actions" {
      [32m+[0m[0m arn                   = (known after apply)
      [32m+[0m[0m assume_role_policy    = (known after apply)
      [32m+[0m[0m create_date           = (known after apply)
      [32m+[0m[0m force_detach_policies = false
      [32m+[0m[0m id                    = (known after apply)
      [32m+[0m[0m managed_policy_arns   = (known after apply)
      [32m+[0m[0m max_session_duration  = 3600
      [32m+[0m[0m name                  = "freebird-dev-github-actions"
      [32m+[0m[0m name_prefix           = (known after apply)
      [32m+[0m[0m path                  = "/"
      [32m+[0m[0m tags                  = {
          [32m+[0m[0m "Name" = "freebird-dev-github-actions"
        }
      [32m+[0m[0m tags_all              = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-github-actions"
          [32m+[0m[0m "Project"     = "freebird"
        }
      [32m+[0m[0m unique_id             = (known after apply)

      [32m+[0m[0m inline_policy (known after apply)
    }

[1m  # module.iam.aws_iam_role_policy.ec2_ecr[0m will be created
[0m  [32m+[0m[0m resource "aws_iam_role_policy" "ec2_ecr" {
      [32m+[0m[0m id          = (known after apply)
      [32m+[0m[0m name        = "ecr-access"
      [32m+[0m[0m name_prefix = (known after apply)
      [32m+[0m[0m policy      = jsonencode(
            {
              [32m+[0m[0m Statement = [
                  [32m+[0m[0m {
                      [32m+[0m[0m Action   = [
                          [32m+[0m[0m "ecr:GetAuthorizationToken",
                          [32m+[0m[0m "ecr:BatchCheckLayerAvailability",
                          [32m+[0m[0m "ecr:GetDownloadUrlForLayer",
                          [32m+[0m[0m "ecr:BatchGetImage",
                        ]
                      [32m+[0m[0m Effect   = "Allow"
                      [32m+[0m[0m Resource = "*"
                    },
                ]
              [32m+[0m[0m Version   = "2012-10-17"
            }
        )
      [32m+[0m[0m role        = (known after apply)
    }

[1m  # module.iam.aws_iam_role_policy.ec2_kms[0m will be created
[0m  [32m+[0m[0m resource "aws_iam_role_policy" "ec2_kms" {
      [32m+[0m[0m id          = (known after apply)
      [32m+[0m[0m name        = "kms-access"
      [32m+[0m[0m name_prefix = (known after apply)
      [32m+[0m[0m policy      = (known after apply)
      [32m+[0m[0m role        = (known after apply)
    }

[1m  # module.iam.aws_iam_role_policy.ec2_logs[0m will be created
[0m  [32m+[0m[0m resource "aws_iam_role_policy" "ec2_logs" {
      [32m+[0m[0m id          = (known after apply)
      [32m+[0m[0m name        = "cloudwatch-logs"
      [32m+[0m[0m name_prefix = (known after apply)
      [32m+[0m[0m policy      = jsonencode(
            {
              [32m+[0m[0m Statement = [
                  [32m+[0m[0m {
                      [32m+[0m[0m Action   = [
                          [32m+[0m[0m "logs:CreateLogGroup",
                          [32m+[0m[0m "logs:CreateLogStream",
                          [32m+[0m[0m "logs:PutLogEvents",
                        ]
                      [32m+[0m[0m Effect   = "Allow"
                      [32m+[0m[0m Resource = "arn:aws:logs:*:877352799272:log-group:/freebird/*"
                    },
                ]
              [32m+[0m[0m Version   = "2012-10-17"
            }
        )
      [32m+[0m[0m role        = (known after apply)
    }

[1m  # module.iam.aws_iam_role_policy.ec2_secrets[0m will be created
[0m  [32m+[0m[0m resource "aws_iam_role_policy" "ec2_secrets" {
      [32m+[0m[0m id          = (known after apply)
      [32m+[0m[0m name        = "secrets-access"
      [32m+[0m[0m name_prefix = (known after apply)
      [32m+[0m[0m policy      = jsonencode(
            {
              [32m+[0m[0m Statement = [
                  [32m+[0m[0m {
                      [32m+[0m[0m Action   = [
                          [32m+[0m[0m "secretsmanager:GetSecretValue",
                          [32m+[0m[0m "secretsmanager:DescribeSecret",
                        ]
                      [32m+[0m[0m Effect   = "Allow"
                      [32m+[0m[0m Resource = "arn:aws:secretsmanager:us-east-1:877352799272:secret:freebird/dev/*"
                    },
                ]
              [32m+[0m[0m Version   = "2012-10-17"
            }
        )
      [32m+[0m[0m role        = (known after apply)
    }

[1m  # module.iam.aws_iam_role_policy.github_ec2[0][0m will be created
[0m  [32m+[0m[0m resource "aws_iam_role_policy" "github_ec2" {
      [32m+[0m[0m id          = (known after apply)
      [32m+[0m[0m name        = "ec2-deploy"
      [32m+[0m[0m name_prefix = (known after apply)
      [32m+[0m[0m policy      = jsonencode(
            {
              [32m+[0m[0m Statement = [
                  [32m+[0m[0m {
                      [32m+[0m[0m Action    = [
                          [32m+[0m[0m "autoscaling:UpdateAutoScalingGroup",
                          [32m+[0m[0m "autoscaling:StartInstanceRefresh",
                          [32m+[0m[0m "autoscaling:DescribeInstanceRefreshes",
                        ]
                      [32m+[0m[0m Condition = {
                          [32m+[0m[0m StringEquals = {
                              [32m+[0m[0m "autoscaling:ResourceTag/Project" = "freebird"
                            }
                        }
                      [32m+[0m[0m Effect    = "Allow"
                      [32m+[0m[0m Resource  = "*"
                    },
                ]
              [32m+[0m[0m Version   = "2012-10-17"
            }
        )
      [32m+[0m[0m role        = (known after apply)
    }

[1m  # module.iam.aws_iam_role_policy.github_ecr[0][0m will be created
[0m  [32m+[0m[0m resource "aws_iam_role_policy" "github_ecr" {
      [32m+[0m[0m id          = (known after apply)
      [32m+[0m[0m name        = "ecr-push"
      [32m+[0m[0m name_prefix = (known after apply)
      [32m+[0m[0m policy      = jsonencode(
            {
              [32m+[0m[0m Statement = [
                  [32m+[0m[0m {
                      [32m+[0m[0m Action   = [
                          [32m+[0m[0m "ecr:GetAuthorizationToken",
                        ]
                      [32m+[0m[0m Effect   = "Allow"
                      [32m+[0m[0m Resource = "*"
                    },
                  [32m+[0m[0m {
                      [32m+[0m[0m Action   = [
                          [32m+[0m[0m "ecr:BatchCheckLayerAvailability",
                          [32m+[0m[0m "ecr:GetDownloadUrlForLayer",
                          [32m+[0m[0m "ecr:BatchGetImage",
                          [32m+[0m[0m "ecr:PutImage",
                          [32m+[0m[0m "ecr:InitiateLayerUpload",
                          [32m+[0m[0m "ecr:UploadLayerPart",
                          [32m+[0m[0m "ecr:CompleteLayerUpload",
                        ]
                      [32m+[0m[0m Effect   = "Allow"
                      [32m+[0m[0m Resource = "arn:aws:ecr:*:877352799272:repository/freebird-*"
                    },
                ]
              [32m+[0m[0m Version   = "2012-10-17"
            }
        )
      [32m+[0m[0m role        = (known after apply)
    }

[1m  # module.kms.aws_kms_alias.enclave[0m will be created
[0m  [32m+[0m[0m resource "aws_kms_alias" "enclave" {
      [32m+[0m[0m arn            = (known after apply)
      [32m+[0m[0m id             = (known after apply)
      [32m+[0m[0m name           = "alias/freebird-dev-enclave"
      [32m+[0m[0m name_prefix    = (known after apply)
      [32m+[0m[0m target_key_arn = (known after apply)
      [32m+[0m[0m target_key_id  = (known after apply)
    }

[1m  # module.kms.aws_kms_key.enclave[0m will be created
[0m  [32m+[0m[0m resource "aws_kms_key" "enclave" {
      [32m+[0m[0m arn                                = (known after apply)
      [32m+[0m[0m bypass_policy_lockout_safety_check = false
      [32m+[0m[0m customer_master_key_spec           = "SYMMETRIC_DEFAULT"
      [32m+[0m[0m deletion_window_in_days            = 30
      [32m+[0m[0m description                        = "KMS key for Freebird enclave keypair encryption"
      [32m+[0m[0m enable_key_rotation                = true
      [32m+[0m[0m id                                 = (known after apply)
      [32m+[0m[0m is_enabled                         = true
      [32m+[0m[0m key_id                             = (known after apply)
      [32m+[0m[0m key_usage                          = "ENCRYPT_DECRYPT"
      [32m+[0m[0m multi_region                       = (known after apply)
      [32m+[0m[0m policy                             = (known after apply)
      [32m+[0m[0m rotation_period_in_days            = (known after apply)
      [32m+[0m[0m tags                               = {
          [32m+[0m[0m "Name" = "freebird-dev-enclave-key"
        }
      [32m+[0m[0m tags_all                           = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-enclave-key"
          [32m+[0m[0m "Project"     = "freebird"
        }
    }

[1m  # module.secrets.aws_secretsmanager_secret.enclave_keypair[0m will be created
[0m  [32m+[0m[0m resource "aws_secretsmanager_secret" "enclave_keypair" {
      [32m+[0m[0m arn                            = (known after apply)
      [32m+[0m[0m description                    = "Encrypted X25519 keypair for enclave. Only attested enclave can decrypt."
      [32m+[0m[0m force_overwrite_replica_secret = false
      [32m+[0m[0m id                             = (known after apply)
      [32m+[0m[0m kms_key_id                     = (known after apply)
      [32m+[0m[0m name                           = "freebird/dev/enclave-keypair"
      [32m+[0m[0m name_prefix                    = (known after apply)
      [32m+[0m[0m policy                         = (known after apply)
      [32m+[0m[0m recovery_window_in_days        = 30
      [32m+[0m[0m tags                           = {
          [32m+[0m[0m "Name" = "freebird-dev-enclave-keypair"
        }
      [32m+[0m[0m tags_all                       = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-enclave-keypair"
          [32m+[0m[0m "Project"     = "freebird"
        }

      [32m+[0m[0m replica (known after apply)
    }

[1m  # module.secrets.aws_secretsmanager_secret.main["clerk_issuer"][0m will be created
[0m  [32m+[0m[0m resource "aws_secretsmanager_secret" "main" {
      [32m+[0m[0m arn                            = (known after apply)
      [32m+[0m[0m force_overwrite_replica_secret = false
      [32m+[0m[0m id                             = (known after apply)
      [32m+[0m[0m kms_key_id                     = (known after apply)
      [32m+[0m[0m name                           = "freebird/dev/clerk_issuer"
      [32m+[0m[0m name_prefix                    = (known after apply)
      [32m+[0m[0m policy                         = (known after apply)
      [32m+[0m[0m recovery_window_in_days        = 30
      [32m+[0m[0m tags                           = {
          [32m+[0m[0m "Name" = "freebird-dev-clerk_issuer"
        }
      [32m+[0m[0m tags_all                       = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-clerk_issuer"
          [32m+[0m[0m "Project"     = "freebird"
        }

      [32m+[0m[0m replica (known after apply)
    }

[1m  # module.secrets.aws_secretsmanager_secret.main["clerk_secret_key"][0m will be created
[0m  [32m+[0m[0m resource "aws_secretsmanager_secret" "main" {
      [32m+[0m[0m arn                            = (known after apply)
      [32m+[0m[0m force_overwrite_replica_secret = false
      [32m+[0m[0m id                             = (known after apply)
      [32m+[0m[0m kms_key_id                     = (known after apply)
      [32m+[0m[0m name                           = "freebird/dev/clerk_secret_key"
      [32m+[0m[0m name_prefix                    = (known after apply)
      [32m+[0m[0m policy                         = (known after apply)
      [32m+[0m[0m recovery_window_in_days        = 30
      [32m+[0m[0m tags                           = {
          [32m+[0m[0m "Name" = "freebird-dev-clerk_secret_key"
        }
      [32m+[0m[0m tags_all                       = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-clerk_secret_key"
          [32m+[0m[0m "Project"     = "freebird"
        }

      [32m+[0m[0m replica (known after apply)
    }

[1m  # module.secrets.aws_secretsmanager_secret.main["clerk_webhook_secret"][0m will be created
[0m  [32m+[0m[0m resource "aws_secretsmanager_secret" "main" {
      [32m+[0m[0m arn                            = (known after apply)
      [32m+[0m[0m force_overwrite_replica_secret = false
      [32m+[0m[0m id                             = (known after apply)
      [32m+[0m[0m kms_key_id                     = (known after apply)
      [32m+[0m[0m name                           = "freebird/dev/clerk_webhook_secret"
      [32m+[0m[0m name_prefix                    = (known after apply)
      [32m+[0m[0m policy                         = (known after apply)
      [32m+[0m[0m recovery_window_in_days        = 30
      [32m+[0m[0m tags                           = {
          [32m+[0m[0m "Name" = "freebird-dev-clerk_webhook_secret"
        }
      [32m+[0m[0m tags_all                       = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-clerk_webhook_secret"
          [32m+[0m[0m "Project"     = "freebird"
        }

      [32m+[0m[0m replica (known after apply)
    }

[1m  # module.secrets.aws_secretsmanager_secret.main["database_url"][0m will be created
[0m  [32m+[0m[0m resource "aws_secretsmanager_secret" "main" {
      [32m+[0m[0m arn                            = (known after apply)
      [32m+[0m[0m force_overwrite_replica_secret = false
      [32m+[0m[0m id                             = (known after apply)
      [32m+[0m[0m kms_key_id                     = (known after apply)
      [32m+[0m[0m name                           = "freebird/dev/database_url"
      [32m+[0m[0m name_prefix                    = (known after apply)
      [32m+[0m[0m policy                         = (known after apply)
      [32m+[0m[0m recovery_window_in_days        = 30
      [32m+[0m[0m tags                           = {
          [32m+[0m[0m "Name" = "freebird-dev-database_url"
        }
      [32m+[0m[0m tags_all                       = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-database_url"
          [32m+[0m[0m "Project"     = "freebird"
        }

      [32m+[0m[0m replica (known after apply)
    }

[1m  # module.secrets.aws_secretsmanager_secret.main["huggingface_token"][0m will be created
[0m  [32m+[0m[0m resource "aws_secretsmanager_secret" "main" {
      [32m+[0m[0m arn                            = (known after apply)
      [32m+[0m[0m force_overwrite_replica_secret = false
      [32m+[0m[0m id                             = (known after apply)
      [32m+[0m[0m kms_key_id                     = (known after apply)
      [32m+[0m[0m name                           = "freebird/dev/huggingface_token"
      [32m+[0m[0m name_prefix                    = (known after apply)
      [32m+[0m[0m policy                         = (known after apply)
      [32m+[0m[0m recovery_window_in_days        = 30
      [32m+[0m[0m tags                           = {
          [32m+[0m[0m "Name" = "freebird-dev-huggingface_token"
        }
      [32m+[0m[0m tags_all                       = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-huggingface_token"
          [32m+[0m[0m "Project"     = "freebird"
        }

      [32m+[0m[0m replica (known after apply)
    }

[1m  # module.secrets.aws_secretsmanager_secret_version.main["clerk_issuer"][0m will be created
[0m  [32m+[0m[0m resource "aws_secretsmanager_secret_version" "main" {
      [32m+[0m[0m arn                  = (known after apply)
      [32m+[0m[0m has_secret_string_wo = (known after apply)
      [32m+[0m[0m id                   = (known after apply)
      [32m+[0m[0m secret_id            = (known after apply)
      [32m+[0m[0m secret_string        = (sensitive value)
      [32m+[0m[0m secret_string_wo     = (write-only attribute)
      [32m+[0m[0m version_id           = (known after apply)
      [32m+[0m[0m version_stages       = (known after apply)
    }

[1m  # module.secrets.aws_secretsmanager_secret_version.main["clerk_secret_key"][0m will be created
[0m  [32m+[0m[0m resource "aws_secretsmanager_secret_version" "main" {
      [32m+[0m[0m arn                  = (known after apply)
      [32m+[0m[0m has_secret_string_wo = (known after apply)
      [32m+[0m[0m id                   = (known after apply)
      [32m+[0m[0m secret_id            = (known after apply)
      [32m+[0m[0m secret_string        = (sensitive value)
      [32m+[0m[0m secret_string_wo     = (write-only attribute)
      [32m+[0m[0m version_id           = (known after apply)
      [32m+[0m[0m version_stages       = (known after apply)
    }

[1m  # module.secrets.aws_secretsmanager_secret_version.main["clerk_webhook_secret"][0m will be created
[0m  [32m+[0m[0m resource "aws_secretsmanager_secret_version" "main" {
      [32m+[0m[0m arn                  = (known after apply)
      [32m+[0m[0m has_secret_string_wo = (known after apply)
      [32m+[0m[0m id                   = (known after apply)
      [32m+[0m[0m secret_id            = (known after apply)
      [32m+[0m[0m secret_string_wo     = (write-only attribute)
      [32m+[0m[0m version_id           = (known after apply)
      [32m+[0m[0m version_stages       = (known after apply)
        [90m# (1 unchanged attribute hidden)[0m[0m
    }

[1m  # module.secrets.aws_secretsmanager_secret_version.main["database_url"][0m will be created
[0m  [32m+[0m[0m resource "aws_secretsmanager_secret_version" "main" {
      [32m+[0m[0m arn                  = (known after apply)
      [32m+[0m[0m has_secret_string_wo = (known after apply)
      [32m+[0m[0m id                   = (known after apply)
      [32m+[0m[0m secret_id            = (known after apply)
      [32m+[0m[0m secret_string        = (sensitive value)
      [32m+[0m[0m secret_string_wo     = (write-only attribute)
      [32m+[0m[0m version_id           = (known after apply)
      [32m+[0m[0m version_stages       = (known after apply)
    }

[1m  # module.secrets.aws_secretsmanager_secret_version.main["huggingface_token"][0m will be created
[0m  [32m+[0m[0m resource "aws_secretsmanager_secret_version" "main" {
      [32m+[0m[0m arn                  = (known after apply)
      [32m+[0m[0m has_secret_string_wo = (known after apply)
      [32m+[0m[0m id                   = (known after apply)
      [32m+[0m[0m secret_id            = (known after apply)
      [32m+[0m[0m secret_string        = (sensitive value)
      [32m+[0m[0m secret_string_wo     = (write-only attribute)
      [32m+[0m[0m version_id           = (known after apply)
      [32m+[0m[0m version_stages       = (known after apply)
    }

[1m  # module.vpc.aws_eip.nat[0m will be created
[0m  [32m+[0m[0m resource "aws_eip" "nat" {
      [32m+[0m[0m allocation_id        = (known after apply)
      [32m+[0m[0m arn                  = (known after apply)
      [32m+[0m[0m association_id       = (known after apply)
      [32m+[0m[0m carrier_ip           = (known after apply)
      [32m+[0m[0m customer_owned_ip    = (known after apply)
      [32m+[0m[0m domain               = "vpc"
      [32m+[0m[0m id                   = (known after apply)
      [32m+[0m[0m instance             = (known after apply)
      [32m+[0m[0m ipam_pool_id         = (known after apply)
      [32m+[0m[0m network_border_group = (known after apply)
      [32m+[0m[0m network_interface    = (known after apply)
      [32m+[0m[0m private_dns          = (known after apply)
      [32m+[0m[0m private_ip           = (known after apply)
      [32m+[0m[0m ptr_record           = (known after apply)
      [32m+[0m[0m public_dns           = (known after apply)
      [32m+[0m[0m public_ip            = (known after apply)
      [32m+[0m[0m public_ipv4_pool     = (known after apply)
      [32m+[0m[0m tags                 = {
          [32m+[0m[0m "Name" = "freebird-dev-nat-eip"
        }
      [32m+[0m[0m tags_all             = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-nat-eip"
          [32m+[0m[0m "Project"     = "freebird"
        }
      [32m+[0m[0m vpc                  = (known after apply)
    }

[1m  # module.vpc.aws_internet_gateway.main[0m will be created
[0m  [32m+[0m[0m resource "aws_internet_gateway" "main" {
      [32m+[0m[0m arn      = (known after apply)
      [32m+[0m[0m id       = (known after apply)
      [32m+[0m[0m owner_id = (known after apply)
      [32m+[0m[0m tags     = {
          [32m+[0m[0m "Name" = "freebird-dev-igw"
        }
      [32m+[0m[0m tags_all = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-igw"
          [32m+[0m[0m "Project"     = "freebird"
        }
      [32m+[0m[0m vpc_id   = (known after apply)
    }

[1m  # module.vpc.aws_nat_gateway.main[0m will be created
[0m  [32m+[0m[0m resource "aws_nat_gateway" "main" {
      [32m+[0m[0m allocation_id                      = (known after apply)
      [32m+[0m[0m association_id                     = (known after apply)
      [32m+[0m[0m connectivity_type                  = "public"
      [32m+[0m[0m id                                 = (known after apply)
      [32m+[0m[0m network_interface_id               = (known after apply)
      [32m+[0m[0m private_ip                         = (known after apply)
      [32m+[0m[0m public_ip                          = (known after apply)
      [32m+[0m[0m secondary_private_ip_address_count = (known after apply)
      [32m+[0m[0m secondary_private_ip_addresses     = (known after apply)
      [32m+[0m[0m subnet_id                          = (known after apply)
      [32m+[0m[0m tags                               = {
          [32m+[0m[0m "Name" = "freebird-dev-nat"
        }
      [32m+[0m[0m tags_all                           = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-nat"
          [32m+[0m[0m "Project"     = "freebird"
        }
    }

[1m  # module.vpc.aws_route_table.private[0m will be created
[0m  [32m+[0m[0m resource "aws_route_table" "private" {
      [32m+[0m[0m arn              = (known after apply)
      [32m+[0m[0m id               = (known after apply)
      [32m+[0m[0m owner_id         = (known after apply)
      [32m+[0m[0m propagating_vgws = (known after apply)
      [32m+[0m[0m route            = [
          [32m+[0m[0m {
              [32m+[0m[0m cidr_block                 = "0.0.0.0/0"
              [32m+[0m[0m nat_gateway_id             = (known after apply)
                [90m# (11 unchanged attributes hidden)[0m[0m
            },
        ]
      [32m+[0m[0m tags             = {
          [32m+[0m[0m "Name" = "freebird-dev-private-rt"
        }
      [32m+[0m[0m tags_all         = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-private-rt"
          [32m+[0m[0m "Project"     = "freebird"
        }
      [32m+[0m[0m vpc_id           = (known after apply)
    }

[1m  # module.vpc.aws_route_table.public[0m will be created
[0m  [32m+[0m[0m resource "aws_route_table" "public" {
      [32m+[0m[0m arn              = (known after apply)
      [32m+[0m[0m id               = (known after apply)
      [32m+[0m[0m owner_id         = (known after apply)
      [32m+[0m[0m propagating_vgws = (known after apply)
      [32m+[0m[0m route            = [
          [32m+[0m[0m {
              [32m+[0m[0m cidr_block                 = "0.0.0.0/0"
              [32m+[0m[0m gateway_id                 = (known after apply)
                [90m# (11 unchanged attributes hidden)[0m[0m
            },
        ]
      [32m+[0m[0m tags             = {
          [32m+[0m[0m "Name" = "freebird-dev-public-rt"
        }
      [32m+[0m[0m tags_all         = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-public-rt"
          [32m+[0m[0m "Project"     = "freebird"
        }
      [32m+[0m[0m vpc_id           = (known after apply)
    }

[1m  # module.vpc.aws_route_table_association.private[0][0m will be created
[0m  [32m+[0m[0m resource "aws_route_table_association" "private" {
      [32m+[0m[0m id             = (known after apply)
      [32m+[0m[0m route_table_id = (known after apply)
      [32m+[0m[0m subnet_id      = (known after apply)
    }

[1m  # module.vpc.aws_route_table_association.private[1][0m will be created
[0m  [32m+[0m[0m resource "aws_route_table_association" "private" {
      [32m+[0m[0m id             = (known after apply)
      [32m+[0m[0m route_table_id = (known after apply)
      [32m+[0m[0m subnet_id      = (known after apply)
    }

[1m  # module.vpc.aws_route_table_association.public[0][0m will be created
[0m  [32m+[0m[0m resource "aws_route_table_association" "public" {
      [32m+[0m[0m id             = (known after apply)
      [32m+[0m[0m route_table_id = (known after apply)
      [32m+[0m[0m subnet_id      = (known after apply)
    }

[1m  # module.vpc.aws_route_table_association.public[1][0m will be created
[0m  [32m+[0m[0m resource "aws_route_table_association" "public" {
      [32m+[0m[0m id             = (known after apply)
      [32m+[0m[0m route_table_id = (known after apply)
      [32m+[0m[0m subnet_id      = (known after apply)
    }

[1m  # module.vpc.aws_subnet.private[0][0m will be created
[0m  [32m+[0m[0m resource "aws_subnet" "private" {
      [32m+[0m[0m arn                                            = (known after apply)
      [32m+[0m[0m assign_ipv6_address_on_creation                = false
      [32m+[0m[0m availability_zone                              = "us-east-1a"
      [32m+[0m[0m availability_zone_id                           = (known after apply)
      [32m+[0m[0m cidr_block                                     = "10.0.32.0/20"
      [32m+[0m[0m enable_dns64                                   = false
      [32m+[0m[0m enable_resource_name_dns_a_record_on_launch    = false
      [32m+[0m[0m enable_resource_name_dns_aaaa_record_on_launch = false
      [32m+[0m[0m id                                             = (known after apply)
      [32m+[0m[0m ipv6_cidr_block_association_id                 = (known after apply)
      [32m+[0m[0m ipv6_native                                    = false
      [32m+[0m[0m map_public_ip_on_launch                        = false
      [32m+[0m[0m owner_id                                       = (known after apply)
      [32m+[0m[0m private_dns_hostname_type_on_launch            = (known after apply)
      [32m+[0m[0m tags                                           = {
          [32m+[0m[0m "Name" = "freebird-dev-private-1"
          [32m+[0m[0m "Type" = "private"
        }
      [32m+[0m[0m tags_all                                       = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-private-1"
          [32m+[0m[0m "Project"     = "freebird"
          [32m+[0m[0m "Type"        = "private"
        }
      [32m+[0m[0m vpc_id                                         = (known after apply)
    }

[1m  # module.vpc.aws_subnet.private[1][0m will be created
[0m  [32m+[0m[0m resource "aws_subnet" "private" {
      [32m+[0m[0m arn                                            = (known after apply)
      [32m+[0m[0m assign_ipv6_address_on_creation                = false
      [32m+[0m[0m availability_zone                              = "us-east-1b"
      [32m+[0m[0m availability_zone_id                           = (known after apply)
      [32m+[0m[0m cidr_block                                     = "10.0.48.0/20"
      [32m+[0m[0m enable_dns64                                   = false
      [32m+[0m[0m enable_resource_name_dns_a_record_on_launch    = false
      [32m+[0m[0m enable_resource_name_dns_aaaa_record_on_launch = false
      [32m+[0m[0m id                                             = (known after apply)
      [32m+[0m[0m ipv6_cidr_block_association_id                 = (known after apply)
      [32m+[0m[0m ipv6_native                                    = false
      [32m+[0m[0m map_public_ip_on_launch                        = false
      [32m+[0m[0m owner_id                                       = (known after apply)
      [32m+[0m[0m private_dns_hostname_type_on_launch            = (known after apply)
      [32m+[0m[0m tags                                           = {
          [32m+[0m[0m "Name" = "freebird-dev-private-2"
          [32m+[0m[0m "Type" = "private"
        }
      [32m+[0m[0m tags_all                                       = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-private-2"
          [32m+[0m[0m "Project"     = "freebird"
          [32m+[0m[0m "Type"        = "private"
        }
      [32m+[0m[0m vpc_id                                         = (known after apply)
    }

[1m  # module.vpc.aws_subnet.public[0][0m will be created
[0m  [32m+[0m[0m resource "aws_subnet" "public" {
      [32m+[0m[0m arn                                            = (known after apply)
      [32m+[0m[0m assign_ipv6_address_on_creation                = false
      [32m+[0m[0m availability_zone                              = "us-east-1a"
      [32m+[0m[0m availability_zone_id                           = (known after apply)
      [32m+[0m[0m cidr_block                                     = "10.0.0.0/20"
      [32m+[0m[0m enable_dns64                                   = false
      [32m+[0m[0m enable_resource_name_dns_a_record_on_launch    = false
      [32m+[0m[0m enable_resource_name_dns_aaaa_record_on_launch = false
      [32m+[0m[0m id                                             = (known after apply)
      [32m+[0m[0m ipv6_cidr_block_association_id                 = (known after apply)
      [32m+[0m[0m ipv6_native                                    = false
      [32m+[0m[0m map_public_ip_on_launch                        = true
      [32m+[0m[0m owner_id                                       = (known after apply)
      [32m+[0m[0m private_dns_hostname_type_on_launch            = (known after apply)
      [32m+[0m[0m tags                                           = {
          [32m+[0m[0m "Name" = "freebird-dev-public-1"
          [32m+[0m[0m "Type" = "public"
        }
      [32m+[0m[0m tags_all                                       = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-public-1"
          [32m+[0m[0m "Project"     = "freebird"
          [32m+[0m[0m "Type"        = "public"
        }
      [32m+[0m[0m vpc_id                                         = (known after apply)
    }

[1m  # module.vpc.aws_subnet.public[1][0m will be created
[0m  [32m+[0m[0m resource "aws_subnet" "public" {
      [32m+[0m[0m arn                                            = (known after apply)
      [32m+[0m[0m assign_ipv6_address_on_creation                = false
      [32m+[0m[0m availability_zone                              = "us-east-1b"
      [32m+[0m[0m availability_zone_id                           = (known after apply)
      [32m+[0m[0m cidr_block                                     = "10.0.16.0/20"
      [32m+[0m[0m enable_dns64                                   = false
      [32m+[0m[0m enable_resource_name_dns_a_record_on_launch    = false
      [32m+[0m[0m enable_resource_name_dns_aaaa_record_on_launch = false
      [32m+[0m[0m id                                             = (known after apply)
      [32m+[0m[0m ipv6_cidr_block_association_id                 = (known after apply)
      [32m+[0m[0m ipv6_native                                    = false
      [32m+[0m[0m map_public_ip_on_launch                        = true
      [32m+[0m[0m owner_id                                       = (known after apply)
      [32m+[0m[0m private_dns_hostname_type_on_launch            = (known after apply)
      [32m+[0m[0m tags                                           = {
          [32m+[0m[0m "Name" = "freebird-dev-public-2"
          [32m+[0m[0m "Type" = "public"
        }
      [32m+[0m[0m tags_all                                       = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-public-2"
          [32m+[0m[0m "Project"     = "freebird"
          [32m+[0m[0m "Type"        = "public"
        }
      [32m+[0m[0m vpc_id                                         = (known after apply)
    }

[1m  # module.vpc.aws_vpc.main[0m will be created
[0m  [32m+[0m[0m resource "aws_vpc" "main" {
      [32m+[0m[0m arn                                  = (known after apply)
      [32m+[0m[0m cidr_block                           = "10.0.0.0/16"
      [32m+[0m[0m default_network_acl_id               = (known after apply)
      [32m+[0m[0m default_route_table_id               = (known after apply)
      [32m+[0m[0m default_security_group_id            = (known after apply)
      [32m+[0m[0m dhcp_options_id                      = (known after apply)
      [32m+[0m[0m enable_dns_hostnames                 = true
      [32m+[0m[0m enable_dns_support                   = true
      [32m+[0m[0m enable_network_address_usage_metrics = (known after apply)
      [32m+[0m[0m id                                   = (known after apply)
      [32m+[0m[0m instance_tenancy                     = "default"
      [32m+[0m[0m ipv6_association_id                  = (known after apply)
      [32m+[0m[0m ipv6_cidr_block                      = (known after apply)
      [32m+[0m[0m ipv6_cidr_block_network_border_group = (known after apply)
      [32m+[0m[0m main_route_table_id                  = (known after apply)
      [32m+[0m[0m owner_id                             = (known after apply)
      [32m+[0m[0m tags                                 = {
          [32m+[0m[0m "Name" = "freebird-dev-vpc"
        }
      [32m+[0m[0m tags_all                             = {
          [32m+[0m[0m "Environment" = "dev"
          [32m+[0m[0m "ManagedBy"   = "terraform"
          [32m+[0m[0m "Name"        = "freebird-dev-vpc"
          [32m+[0m[0m "Project"     = "freebird"
        }
    }

[1mPlan:[0m [0m44 to add, 0 to change, 0 to destroy.

Changes to Outputs:
  [32m+[0m[0m alb_dns_name            = (known after apply)
  [32m+[0m[0m alb_zone_id             = (known after apply)
  [32m+[0m[0m ec2_role_arn            = (known after apply)
  [32m+[0m[0m github_actions_role_arn = (known after apply)
  [32m+[0m[0m kms_key_arn             = (known after apply)
  [32m+[0m[0m kms_key_id              = (known after apply)
  [32m+[0m[0m private_subnet_ids      = [
      [32m+[0m[0m (known after apply),
      [32m+[0m[0m (known after apply),
    ]
  [32m+[0m[0m public_subnet_ids       = [
      [32m+[0m[0m (known after apply),
      [32m+[0m[0m (known after apply),
    ]
  [32m+[0m[0m secrets_arn_prefix      = "arn:aws:secretsmanager:us-east-1:877352799272:secret:freebird/dev/"
  [32m+[0m[0m vpc_id                  = (known after apply)
