# weather-api (prod) → localhost:9091
kubectl port-forward svc/weather-api -n weather 9091:80  &>/dev/null &

# weather-api (dev) → localhost:9092
kubectl port-forward svc/weather-api -n weather-dev 9092:80  &>/dev/null &

# alert-agent → localhost:9093
kubectl port-forward svc/alert-agent -n weather-agent 9093:80  &>/dev/null &