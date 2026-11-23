execute as @a at @s if block ~ ~-1 ~ minecraft:campfire[lit=true] run scoreboard players add @s campfire_time 1
execute as @a[scores={campfire_time=100..}] run function campfire:reward
# 줄 이어 쓰기
execute as @a \
    at @s run particle minecraft:flame ~ ~1 ~ 0.1 0.1 0.1 0.01 2
