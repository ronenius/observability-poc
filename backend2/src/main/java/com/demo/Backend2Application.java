package com.demo;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import io.prometheus.client.Counter;
import io.prometheus.client.CollectorRegistry;
import io.prometheus.client.exporter.common.TextFormat;

import java.io.IOException;
import java.io.StringWriter;
import java.util.Map;
import java.util.Random;

@SpringBootApplication
@RestController
public class Backend2Application {

    private static final Logger logger = LogManager.getLogger(Backend2Application.class);
    private final Random random = new Random();

    // Prometheus Metric Definition
    private static final Counter requestCounter = Counter.build()
            .name("app_requests_total")
            .help("Total number of requests received")
            .register();

    public static void main(String[] args) {
        SpringApplication.run(Backend2Application.class, args);
    }

    // Exposes the Prometheus metrics endpoint
    @GetMapping(value = "/metrics", produces = TextFormat.CONTENT_TYPE_004)
    public String metrics() throws IOException {
        StringWriter writer = new StringWriter();
        TextFormat.write004(writer, CollectorRegistry.defaultRegistry.metricFamilySamples());
        return writer.toString();
    }

    @GetMapping("/api/data")
    public Map<String, String> getData() {
        // Increment the counter on request
        requestCounter.inc();
        logger.info("Backend 2 received a request. Processing data...");

        // 10% failure probability
        if (random.nextDouble() < 0.10) {
            logger.error("Simulated 10% failure triggered in Backend 2");
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "Backend 2 failed randomly");
        }

        return Map.of("source", "backend2", "message", "Hello from Java Backend");
    }
}