var coll = document.getElementsByClassName("collbutton");
var i;

for (i = 0; i < coll.length; i++) {
  coll[i].addEventListener("click", function() {
    this.classList.toggle("active");
    var content = this.nextElementSibling;  
    content.classList.toggle("inactive_content");
    });
};
