give @s minecraft:diamond 1
effect give @s minecraft:regeneration 5 1 true
scoreboard players set @s campfire_time 0
function campfire:macro_say {name:"보상"}
schedule function #campfire:later 1s
