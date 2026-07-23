package com.demo;

import org.apache.logging.log4j.LogManager;
import org.apache.logging.log4j.Logger;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;
import java.util.Random;

@SpringBootApplication
@RestController
@RequestMapping("/api")
public class Backend2Application {

    private static final Logger logger = LogManager.getLogger(Backend2Application.class);
    private final Random random = new Random();

    public static void main(String[] args) {
        SpringApplication.run(Backend2Application.class, args);
    }

    @GetMapping("/data")
    public Map<String, String> getData() {
        logger.info("Backend 2 received a request. Processing data...");

        // 10% failure probability
        if (random.nextDouble() < 0.10) {
            logger.error("Simulated 10% failure triggered in Backend 2");
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "Backend 2 failed randomly");
        }

        return Map.of("source", "backend2", "message", "Hello from Java Backend");
    }
}