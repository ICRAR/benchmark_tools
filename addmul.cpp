#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include <sys/time.h>
 
// g++ -std=c++11 -o addmul addmul.cpp
// all values are chosen to avoid IEEE754 rounding errors and make sure
// that the directly calculated expected values match the iterated ones.
 
double stoptime(void)
{
   struct timeval t;
   gettimeofday(&t, NULL);
   return (double)t.tv_sec + t.tv_usec / 1000000.0;
}
 
double addmul(double add, double mul, long ops)
{
   // need to initialise differently otherwise compiler might optimise away
   double sum1 = 0.125, sum2 = -0.125, sum3 = 0.0625, sum4 = -0.0625, sum5 = 0.0;
   double mul1 = 1./2e1, mul2 = 1./2e2, mul3 = 1./2e3, mul4 = 1./2e4, mul5 = 1./2e5;
   long loops = ops / 10; // we have 10 floating point ops inside the loop
   double expected_sum = 5.0 * add * loops + (sum1 + sum2 + sum3 + sum4 + sum5);
   double expected_mul = pow(mul, loops) * (mul1 + mul2 + mul3 + mul4 + mul5);

   for (long i = 0; i < loops; i++)
   {
      mul1 *= mul;
      mul2 *= mul;
      mul3 *= mul;
      mul4 *= mul;
      mul5 *= mul;
      sum1 += add;
      sum2 += add;
      sum3 += add;
      sum4 += add;
      sum5 += add;
   }
   double res_sum = sum1 + sum2 + sum3 + sum4 + sum5 - expected_sum;
   double res_mul = mul1 + mul2 + mul3 + mul4 + mul5 - expected_mul;
   return res_sum + res_mul;
}
 
int main(int argc, char **argv)
{
   if (argc != 2)
   {
      printf("usage: %s <num>\n", argv[0]);
      printf("number of operations: <num> millions\n");
      exit(EXIT_FAILURE);
   }
   long n = (long)(atof(argv[1]) * 1000000);
   if (n <= 0)
      n = 1000;
 
   double x = 3.0000019073486328125;
   double y = 9.5367431640625e-7;
   double t = stoptime();
   x = addmul(x, y, n);
   t = stoptime() - t;
   printf("addmul:\t %.3f s, %.3f Gflops, N=%ld, res=%f\n", t, (double)n / t / 1e9, n, x);
 
   return EXIT_SUCCESS;
}
