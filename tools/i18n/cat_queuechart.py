E = {
"En attente (pic)": "Waiting (peak)",
"En cours": "Running",
}
P = [
(r"En attente \(pic\) : (.+)", "Waiting (peak): {1}"),
(r"En cours : (.+)", "Running: {1}"),
]
